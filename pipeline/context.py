"""Scoring context loading: the preparation record to the pool index.

Spec: docs/specs/scoring-path.md section 7. The committed preparation
record plus its artifact tree is the full interface between the
preparation pipeline and the scoring path. Loading checks each file it
reads against the record's artifact inventory, recomputes the identity
hashes, and reads the canonical render values from the preparation
config file — the one source R2 permits. Drift after release stops the
load with the path named.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import sha256_hex
from core.types import (ChannelName, ElementConfig, IntakeGates, OutlineConfig,
                        PlacementConfig, PoolIndex, PoolScores, RenderParams,
                        ScoringContext, Weights)
from pool.artifacts import ManifestError
from pool.preparation import manifest as mf
from pool.preparation.config import ConfigError, load_preparation_config
from pool.preparation.config import preparation_config_hash as prep_hash
from pool.preparation.stages.outline import ROW_LAYOUT
from pool.preparation.stages.release import release_preparation_version_id
from pool.preparation.types import GroupRow, PreparationTree

_HEX64_CHARS = set("0123456789abcdef")

_USED_FIELDS = ("label", "preparation_version_id", "preparation_config_hash",
                "config_path", "image_count", "artifacts", "pool",
                "provider_config_hashes", "dev_only")
_DISCARDED_FIELDS = ("code_version", "created_at", "provider_usage")
_POOL_FIELDS = ("label", "pool_version_id", "release_record_path")

# The artifact keys the scoring path reads (spec P2 section 7, spec
# P3 section 7, and spec P4 section 7).
_RECORDS_KEY = "p00-intake/records.jsonl"
_VECTORS_KEY = "p06-outline/outline_vectors.npy"
_MEAN_KEY = "p06-outline/outline_space_mean.npy"
_GROUPS_KEY = "p08-neardup/groups.jsonl"
_VOCABULARY_KEY = "p04-vocabulary/vocabulary.jsonl"
_ELEMENT_VECTORS_KEY = "p04-vocabulary/vocabulary_vectors.npy"
_INCIDENCE_KEY = "p04-vocabulary/incidence.npy"
_ELEMENT_MEAN_KEY = "p04-vocabulary/element_space_mean.npy"
_BOXES_KEY = "p07-boxes/boxes.jsonl"

# Unit-norm tolerance for the stored element vectors. The p04 stage
# applies the same value when it writes them.
_NORM_TOLERANCE = 1e-3


class ContextError(ManifestError):
    """A preparation record or artifact did not parse or reconcile."""


@dataclass(frozen=True, slots=True)
class PreparationRecord:
    """The parsed committed preparation record (P1b section 10, p09)."""

    label: str
    preparation_version_id: str
    preparation_config_hash: str
    config_path: str
    image_count: int
    artifacts: tuple[tuple[str, str], ...]
    pool_label: str
    pool_version_id: str
    pool_release_record_path: str
    provider_config_hashes: tuple[tuple[str, str], ...]
    dev_only: bool


class LoadedPreparation(NamedTuple):
    """One verified preparation: record, pool index, render values."""

    record: PreparationRecord
    index: PoolIndex
    render: RenderParams


class ElementSide(NamedTuple):
    """The p04 and p07 artifacts as one bundle (spec P3 section 7,
    spec P4 section 7).

    vocabulary holds B entry strings and pool_frequency the document
    frequency of the first V of them, which are the pool vocabulary.
    The V1 union builder appends entries above V and keeps the first V
    and pool_image_count as they are, so rarity stays pool-defined.
    box_table (N, k, 4) and box_mask (N, k) are slot-aligned with
    incidence — a masked-out slot holds zeros and no box.
    """

    vocabulary: tuple[str, ...]
    pool_frequency: tuple[int, ...]
    pool_image_count: int
    vocabulary_vectors: np.ndarray
    incidence: np.ndarray
    element_space_mean: np.ndarray
    box_table: np.ndarray
    box_mask: np.ndarray


def _checked_hex64(value: object, where: str) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or not set(value) <= _HEX64_CHARS):
        raise ContextError(f"{where}: expected a 64-character hex digest")
    return value


def _checked_str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContextError(f"{where}: expected a non-empty string")
    return value


def parse_preparation_record(raw: object, source: str) -> PreparationRecord:
    """Parse one preparation record document, with strict rules.

    Unknown and missing fields cause one aggregate error with sorted
    names. The discarded fields are consumed unchecked — the record
    and the artifact tree are the full interface.
    """
    if not isinstance(raw, dict):
        raise ContextError(f"{source}: expected an object")
    fields = dict(raw)
    known = set(_USED_FIELDS) | set(_DISCARDED_FIELDS)
    unknown = sorted(set(fields) - known)
    missing = sorted(known - set(fields))
    if unknown or missing:
        parts = []
        if unknown:
            parts.append(f"unknown field(s): {', '.join(unknown)}")
        if missing:
            parts.append(f"missing field(s): {', '.join(missing)}")
        raise ContextError(f"{source}: {'; '.join(parts)}")

    pool = fields["pool"]
    if not isinstance(pool, dict) or set(pool) != set(_POOL_FIELDS):
        raise ContextError(
            f"{source}.pool: expected the keys {sorted(_POOL_FIELDS)}")

    artifacts = fields["artifacts"]
    if not isinstance(artifacts, dict) or not artifacts:
        raise ContextError(f"{source}.artifacts: expected a non-empty object")
    artifact_pairs = tuple(
        (_checked_str(key, f"{source}.artifacts"),
         _checked_hex64(artifacts[key], f"{source}.artifacts.{key}"))
        for key in sorted(artifacts))

    hashes = fields["provider_config_hashes"]
    if not isinstance(hashes, dict):
        raise ContextError(
            f"{source}.provider_config_hashes: expected an object")
    hash_pairs = tuple(
        (key, _checked_hex64(hashes[key],
                             f"{source}.provider_config_hashes.{key}"))
        for key in sorted(hashes))

    image_count = fields["image_count"]
    if not isinstance(image_count, int) or isinstance(image_count, bool) \
            or image_count < 1:
        raise ContextError(f"{source}.image_count: expected a positive integer")

    dev_only = fields["dev_only"]
    if not isinstance(dev_only, bool):
        raise ContextError(f"{source}.dev_only: expected a boolean")

    return PreparationRecord(
        label=_checked_str(fields["label"], f"{source}.label"),
        preparation_version_id=_checked_hex64(
            fields["preparation_version_id"],
            f"{source}.preparation_version_id"),
        preparation_config_hash=_checked_hex64(
            fields["preparation_config_hash"],
            f"{source}.preparation_config_hash"),
        config_path=_checked_str(fields["config_path"], f"{source}.config_path"),
        image_count=image_count,
        artifacts=artifact_pairs,
        pool_label=_checked_str(pool["label"], f"{source}.pool.label"),
        pool_version_id=_checked_hex64(
            pool["pool_version_id"], f"{source}.pool.pool_version_id"),
        pool_release_record_path=_checked_str(
            pool["release_record_path"], f"{source}.pool.release_record_path"),
        provider_config_hashes=hash_pairs,
        dev_only=dev_only,
    )


def load_preparation_record(path: Path) -> PreparationRecord:
    """Read and parse the committed preparation record at path."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContextError(f"{path}: cannot read record: {error}") from error
    return parse_preparation_record(raw, source=str(path))


def _checked_element_side(elements: ElementSide, count: int) -> None:
    """Make sure the element artifacts agree with each other (P3 R11).

    Checks: a non-empty vocabulary with no duplicate string, unit-norm
    float32 vectors aligned with it, document frequencies in
    [1, pool image count], and an incidence table of int32 rows that
    index the vocabulary, pad with -1 at the end alone, name no entry
    two times, and let no image stay without an element.
    """
    bank_count = len(elements.vocabulary)
    entry_count = len(elements.pool_frequency)
    if entry_count == 0:
        raise ContextError("the pool vocabulary is empty")
    if bank_count < entry_count:
        raise ContextError(
            f"the element bank holds {bank_count} entries, fewer than the "
            f"{entry_count} pool vocabulary entries")
    if len(set(elements.vocabulary)) != bank_count:
        raise ContextError("the element bank repeats an entry string")
    if elements.pool_image_count < 1:
        raise ContextError("pool_image_count must be positive")
    if any(not 1 <= frequency <= elements.pool_image_count
           for frequency in elements.pool_frequency):
        raise ContextError(
            "each pool_frequency must be in [1, pool_image_count]")

    vectors = elements.vocabulary_vectors
    if vectors.ndim != 2 or vectors.shape[0] != bank_count:
        raise ContextError(
            f"vocabulary_vectors must have shape ({bank_count}, d), got "
            f"{vectors.shape}")
    if vectors.dtype != np.float32:
        raise ContextError(
            f"vocabulary_vectors must be float32, got {vectors.dtype}")
    if not np.isfinite(vectors).all():
        raise ContextError("vocabulary_vectors holds a non-finite value")
    norms = np.linalg.norm(vectors, axis=1)                     # (B,)
    if bool((np.abs(norms - 1.0) > _NORM_TOLERANCE).any()):
        raise ContextError("vocabulary_vectors rows are not unit-norm")
    dimension = vectors.shape[1]
    if (elements.element_space_mean.shape != (dimension,)
            or elements.element_space_mean.dtype != np.float32):
        raise ContextError(
            f"element_space_mean must be float32 ({dimension},), got "
            f"{elements.element_space_mean.dtype} "
            f"{elements.element_space_mean.shape}")

    incidence = elements.incidence
    if incidence.ndim != 2 or incidence.shape[0] != count:
        raise ContextError(
            f"incidence must have shape ({count}, k), got {incidence.shape}")
    if incidence.dtype != np.int32:
        raise ContextError(f"incidence must be int32, got {incidence.dtype}")
    if incidence.size and (int(incidence.min()) < -1
                           or int(incidence.max()) >= bank_count):
        raise ContextError(
            f"incidence entries must be in [-1, {bank_count})")
    for position in range(count):
        row = incidence[position]
        kept = row[row >= 0]
        if kept.shape[0] == 0:
            raise ContextError(
                f"image at position {position} has no element")
        if not bool((row[:kept.shape[0]] >= 0).all()):
            raise ContextError(
                f"incidence row {position} pads before its last entry")
        if len(set(kept.tolist())) != kept.shape[0]:
            raise ContextError(
                f"incidence row {position} names an entry twice")
    _checked_box_side(elements, count)


def _checked_box_side(elements: ElementSide, count: int) -> None:
    """Make sure the box side aligns with the incidence table (P4 R11).

    Checks: box_table (N, k, 4) float32 and box_mask (N, k) bool with
    the incidence width, no box on a padding slot, and the box of each
    on slot finite, in the unit square, with a positive width and
    height. An off slot must hold zeros — a stale value in an off slot
    reads as data to a person inspecting the array.
    """
    width = elements.incidence.shape[1]
    table = elements.box_table
    mask = elements.box_mask
    if table.shape != (count, width, 4):
        raise ContextError(
            f"box_table must have shape ({count}, {width}, 4), got "
            f"{table.shape}")
    if table.dtype != np.float32:
        raise ContextError(f"box_table must be float32, got {table.dtype}")
    if mask.shape != (count, width):
        raise ContextError(
            f"box_mask must have shape ({count}, {width}), got {mask.shape}")
    if mask.dtype != np.bool_:
        raise ContextError(f"box_mask must be bool, got {mask.dtype}")
    if bool((mask & (elements.incidence < 0)).any()):
        raise ContextError("box_mask marks a padding slot")
    if bool((table[~mask] != 0.0).any()):
        raise ContextError("box_table holds a value behind a false mask")
    kept = table[mask]                                          # (rows, 4)
    if kept.size == 0:
        return
    if not np.isfinite(kept).all():
        raise ContextError("box_table holds a non-finite value")
    if bool((kept < 0.0).any()) or bool((kept > 1.0).any()):
        raise ContextError("box coordinates must be in [0, 1]")
    if bool((kept[:, 2] <= kept[:, 0]).any()) \
            or bool((kept[:, 3] <= kept[:, 1]).any()):
        raise ContextError("a box has no extent on one axis")


def build_pool_index(index_id: str, image_ids: tuple[str, ...],
                     outline_vectors: np.ndarray,
                     outline_space_mean: np.ndarray,
                     group_rows: tuple[GroupRow, ...],
                     elements: ElementSide) -> PoolIndex:
    """Make sure the tables align, then build one pool index.

    Public: the V1 union builder reuses it (D7). Checks: ascending
    unique image_ids, aligned float32 arrays with the p06 row layout,
    group rows aligned with the ids, each group identifier the
    smallest member, member counts that agree with the tally, and the
    element side of _checked_element_side.
    """
    count = len(image_ids)
    if count == 0:
        raise ContextError("the index has no images")
    if any(image_ids[i] >= image_ids[i + 1] for i in range(count - 1)):
        raise ContextError("image_ids must be ascending with no repeats")
    if (outline_vectors.ndim != 3
            or outline_vectors.shape[0] != count
            or outline_vectors.shape[1] != len(ROW_LAYOUT)):
        raise ContextError(
            f"outline_vectors must have shape ({count}, {len(ROW_LAYOUT)}, d), "
            f"got {outline_vectors.shape}")
    if outline_vectors.dtype != np.float32:
        raise ContextError(
            f"outline_vectors must be float32, got {outline_vectors.dtype}")
    dimension = outline_vectors.shape[2]
    if (outline_space_mean.shape != (dimension,)
            or outline_space_mean.dtype != np.float32):
        raise ContextError(
            f"outline_space_mean must be float32 ({dimension},), got "
            f"{outline_space_mean.dtype} {outline_space_mean.shape}")
    if tuple(row.image_id for row in group_rows) != image_ids:
        raise ContextError(
            "group rows must cover the image_ids in the same sequence")
    members: dict[str, list[str]] = {}
    for row in group_rows:
        members.setdefault(row.group_id, []).append(row.image_id)
    for row in group_rows:
        group_members = members[row.group_id]
        if row.group_id != min(group_members):
            raise ContextError(
                f"group {row.group_id} is not the smallest member")
        if row.member_count != len(group_members):
            raise ContextError(
                f"group {row.group_id}: member_count {row.member_count} does "
                f"not agree with the tally {len(group_members)}")
    _checked_element_side(elements, count)
    return PoolIndex(
        index_id=index_id,
        image_ids=image_ids,
        outline_vectors=outline_vectors,
        outline_space_mean=outline_space_mean,
        group_ids=tuple(row.group_id for row in group_rows),
        pool_image_count=elements.pool_image_count,
        vocabulary=elements.vocabulary,
        pool_frequency=elements.pool_frequency,
        vocabulary_vectors=elements.vocabulary_vectors,
        incidence=elements.incidence,
        element_space_mean=elements.element_space_mean,
        box_table=elements.box_table,
        box_mask=elements.box_mask,
    )


def _verified_bytes(tree_root: Path, inventory: dict[str, str],
                    key: str) -> bytes:
    """Read one artifact and check it against the inventory digest."""
    if key not in inventory:
        raise ContextError(f"artifact inventory has no entry for {key}")
    path = tree_root / key
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ContextError(f"{path}: cannot read artifact: {error}") from error
    measured = sha256_hex(data)
    if measured != inventory[key]:
        raise ContextError(
            f"{path}: digest {measured} does not agree with the record "
            f"inventory {inventory[key]}")
    return data


def _jsonl_rows(data: bytes, where: str) -> list[dict]:
    rows = []
    for line_number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ContextError(
                f"{where}:{line_number}: cannot parse row: {error}") from error
        if not isinstance(row, dict):
            raise ContextError(f"{where}:{line_number}: expected an object")
        rows.append(row)
    return rows


def _checked_vocabulary_rows(rows: list[dict]) -> None:
    """The p04 row rules: ascending indices from zero, no gaps."""
    if not rows:
        raise ContextError(f"{_VOCABULARY_KEY}: no rows")
    for position, row in enumerate(rows):
        if row.get("index") != position:
            raise ContextError(
                f"{_VOCABULARY_KEY}:{position + 1}: index "
                f"{row.get('index')!r} is not the row position")


def _vocabulary_strings(rows: list[dict]) -> tuple[str, ...]:
    """The entry strings of the p04 vocabulary, in index sequence."""
    _checked_vocabulary_rows(rows)
    return tuple(
        _checked_str(row.get("element"), f"{_VOCABULARY_KEY}:{number + 1}")
        for number, row in enumerate(rows))


def _vocabulary_frequencies(rows: list[dict]) -> tuple[int, ...]:
    """The document frequencies of the p04 vocabulary, in index sequence."""
    _checked_vocabulary_rows(rows)
    frequencies = []
    for number, row in enumerate(rows):
        value = row.get("pool_frequency")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ContextError(
                f"{_VOCABULARY_KEY}:{number + 1}: pool_frequency "
                f"{value!r} is not a positive integer")
        frequencies.append(value)
    return tuple(frequencies)


def box_side(box_rows: list[dict], image_ids: tuple[str, ...],
             vocabulary: tuple[str, ...],
             incidence: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The p07 rows as slot-aligned arrays (spec P4 section 7).

    The stored rows map element strings to boxes in lexicographic key
    sequence — canonical JSON sorts the keys — thus the incidence
    table aligns the slots and the stored sequence does not:
    slot j of image i holds the box of vocabulary[incidence[i, j]].
    Public: the fixture builders and the union path use it again.

    Checks here mirror the p07 boundary rules (boxes_validate): the
    row sequence equals image_ids, each row's key set equals the
    image's element strings, and each box is four numbers in [0, 1]
    with a positive width and height. A null box and a padding slot
    keep the slot off and the table row zero.
    """
    if len(box_rows) != len(image_ids):
        raise ContextError(
            f"{_BOXES_KEY}: {len(box_rows)} rows do not agree with "
            f"{len(image_ids)} images")
    width = incidence.shape[1]
    table = np.zeros((len(image_ids), width, 4), dtype=np.float32)
    mask = np.zeros((len(image_ids), width), dtype=np.bool_)
    for position, row in enumerate(box_rows):
        where = f"{_BOXES_KEY}:{position + 1}"
        if row.get("image_id") != image_ids[position]:
            raise ContextError(
                f"{where}: image_id {row.get('image_id')!r} is not "
                f"{image_ids[position]!r} — rows must follow the p00 "
                "sequence")
        boxes = row.get("boxes")
        if not isinstance(boxes, dict):
            raise ContextError(f"{where}: boxes is not an object")
        slots = incidence[position]
        expected = {vocabulary[int(entry)] for entry in slots if entry >= 0}
        if set(boxes) != expected:
            missing = sorted(expected - set(boxes))
            extra = sorted(set(boxes) - expected)
            raise ContextError(
                f"{where}: box keys do not equal the element list "
                f"(missing {missing}, extra {extra})")
        for slot, entry in enumerate(slots):
            if entry < 0:
                continue
            value = boxes[vocabulary[int(entry)]]
            if value is None:
                continue
            if (not isinstance(value, list) or len(value) != 4
                    or any(isinstance(v, bool)
                           or not isinstance(v, (int, float))
                           for v in value)):
                raise ContextError(
                    f"{where}: a box must be four numbers or null")
            x_min, y_min, x_max, y_max = (float(v) for v in value)
            if not (0.0 <= x_min < x_max <= 1.0
                    and 0.0 <= y_min < y_max <= 1.0):
                raise ContextError(
                    f"{where}: box {value} is not in the unit square with "
                    "a positive extent")
            table[position, slot] = (x_min, y_min, x_max, y_max)
            mask[position, slot] = True
    return table, mask


def load_pool_index(record_path: Path, data_root: Path, *,
                    dev_only: bool) -> LoadedPreparation:
    """Load and check one prepared pool (spec section 7).

    The sequence: parse the record, check the dev_only gate, recompute
    the preparation version identity, recompute the preparation config
    hash from the config file (which also delivers the render values —
    R2), then read and digest-check each artifact the scoring path
    uses.
    """
    record = load_preparation_record(record_path)
    if record.dev_only != dev_only:
        raise ContextError(
            f"{record_path}: record dev_only={record.dev_only} does not "
            f"agree with the config dev_only={dev_only}")

    recomputed = release_preparation_version_id(
        record.pool_version_id, record.preparation_config_hash)
    if recomputed != record.preparation_version_id:
        raise ContextError(
            f"{record_path}: preparation_version_id does not agree with "
            "the recomputed identity")

    try:
        prep_config = load_preparation_config(Path(record.config_path))
    except ConfigError as error:
        raise ContextError(
            f"{record.config_path}: cannot load the preparation config: "
            f"{error}") from error
    measured_hash = prep_hash(prep_config, dict(record.provider_config_hashes))
    if measured_hash != record.preparation_config_hash:
        raise ContextError(
            f"{record.config_path}: the config file hash {measured_hash[:8]} "
            "does not agree with the record — the file moved after release")
    if prep_config.linedraw.antialias or prep_config.linedraw.background != "white":
        raise ContextError(
            "the stroke render implements white background with no "
            "anti-aliasing only — the preparation config says different")
    render = RenderParams(canvas_px=prep_config.linedraw.canvas_px,
                          line_width_px=prep_config.linedraw.line_width_px)

    tree = PreparationTree(
        data_root=data_root,
        pool_version_id=record.pool_version_id,
        preparation_config_hash=record.preparation_config_hash,
        pool_label=record.pool_label,
    )
    tree_root = mf.stage_dir(tree, "p00-intake").parent
    inventory = dict(record.artifacts)

    record_rows = _jsonl_rows(
        _verified_bytes(tree_root, inventory, _RECORDS_KEY), _RECORDS_KEY)
    image_ids = tuple(str(row["image_id"]) for row in record_rows)
    if len(image_ids) != record.image_count:
        raise ContextError(
            f"{_RECORDS_KEY}: {len(image_ids)} rows do not agree with "
            f"image_count {record.image_count}")

    outline_vectors = np.load(
        BytesIO(_verified_bytes(tree_root, inventory, _VECTORS_KEY)))
    outline_space_mean = np.load(
        BytesIO(_verified_bytes(tree_root, inventory, _MEAN_KEY)))
    group_rows = tuple(
        mf.row_to_group(row) for row in _jsonl_rows(
            _verified_bytes(tree_root, inventory, _GROUPS_KEY), _GROUPS_KEY))

    vocabulary_rows = _jsonl_rows(
        _verified_bytes(tree_root, inventory, _VOCABULARY_KEY),
        _VOCABULARY_KEY)
    vocabulary = _vocabulary_strings(vocabulary_rows)
    incidence = np.load(
        BytesIO(_verified_bytes(tree_root, inventory, _INCIDENCE_KEY)))
    box_rows = _jsonl_rows(
        _verified_bytes(tree_root, inventory, _BOXES_KEY), _BOXES_KEY)
    box_table, box_mask = box_side(box_rows, image_ids, vocabulary,
                                   incidence)
    elements = ElementSide(
        vocabulary=vocabulary,
        pool_frequency=_vocabulary_frequencies(vocabulary_rows),
        pool_image_count=len(image_ids),
        vocabulary_vectors=np.load(
            BytesIO(_verified_bytes(tree_root, inventory,
                                    _ELEMENT_VECTORS_KEY))),
        incidence=incidence,
        element_space_mean=np.load(
            BytesIO(_verified_bytes(tree_root, inventory,
                                    _ELEMENT_MEAN_KEY))),
        box_table=box_table,
        box_mask=box_mask,
    )

    index = build_pool_index(
        index_id=record.preparation_version_id,
        image_ids=image_ids,
        outline_vectors=outline_vectors,
        outline_space_mean=outline_space_mean,
        group_rows=group_rows,
        elements=elements,
    )
    return LoadedPreparation(record=record, index=index, render=render)


def build_scoring_context(index: PoolIndex, gates: IntakeGates,
                          render: RenderParams, outline: OutlineConfig,
                          element: ElementConfig,
                          placement: PlacementConfig, weights: Weights,
                          commonness: Mapping[ChannelName, PoolScores],
                          scoring_config_hash: str,
                          commonness_config_hash: str) -> ScoringContext:
    """Assemble one frozen context, with table checks.

    The stored artifact holds a table for each built channel the
    background activates (ruling 2026-08-10) — the context selects
    the weighted subset here, because a table for a channel with no
    weight is inert. The kept set can also be smaller than the
    weighted set: a submission mode that leaves a channel silent
    builds no table for it (spec P3 section 10), and a trial that
    activates a channel with no table raises in score_trial rather
    than scoring around it. Each kept table must have length N.
    """
    count = len(index.image_ids)
    kept = {name: table for name, table in commonness.items()
            if name in weights}
    for name, table in kept.items():
        if table.shape != (count,) or table.dtype != np.float32:
            raise ContextError(
                f"commonness table {name!r} must be float32 ({count},), got "
                f"{table.dtype} {table.shape}")
    return ScoringContext(
        index=index, gates=gates, render=render, outline=outline,
        element=element, placement=placement, weights=weights,
        commonness=kept,
        scoring_config_hash=scoring_config_hash,
        commonness_config_hash=commonness_config_hash,
    )
