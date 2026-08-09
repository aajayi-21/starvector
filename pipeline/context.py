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
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import sha256_hex
from core.types import (ChannelName, IntakeGates, OutlineConfig, PoolIndex,
                        PoolScores, RenderParams, ScoringContext, Weights)
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

# The artifact keys the scoring path reads (spec section 7). Element
# artifacts stay unread in this phase.
_RECORDS_KEY = "p00-intake/records.jsonl"
_VECTORS_KEY = "p06-outline/outline_vectors.npy"
_MEAN_KEY = "p06-outline/outline_space_mean.npy"
_GROUPS_KEY = "p08-neardup/groups.jsonl"


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


def build_pool_index(index_id: str, image_ids: tuple[str, ...],
                     outline_vectors: np.ndarray,
                     outline_space_mean: np.ndarray,
                     group_rows: tuple[GroupRow, ...]) -> PoolIndex:
    """Make sure the tables align, then build one pool index.

    Public: the V1 union builder reuses it (D7). Checks: ascending
    unique image_ids, aligned float32 arrays with the p06 row layout,
    group rows aligned with the ids, each group identifier the
    smallest member, and member counts that agree with the tally.
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
    return PoolIndex(
        index_id=index_id,
        image_ids=image_ids,
        outline_vectors=outline_vectors,
        outline_space_mean=outline_space_mean,
        group_ids=tuple(row.group_id for row in group_rows),
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

    index = build_pool_index(
        index_id=record.preparation_version_id,
        image_ids=image_ids,
        outline_vectors=outline_vectors,
        outline_space_mean=outline_space_mean,
        group_rows=group_rows,
    )
    return LoadedPreparation(record=record, index=index, render=render)


def build_scoring_context(index: PoolIndex, gates: IntakeGates,
                          render: RenderParams, outline: OutlineConfig,
                          weights: Weights,
                          commonness: dict[ChannelName, PoolScores],
                          scoring_config_hash: str,
                          commonness_config_hash: str) -> ScoringContext:
    """Assemble one frozen context, with table checks.

    Each weighted channel must have a commonness table of length N —
    a missing table is a configuration bug, not a skip (R14).
    """
    count = len(index.image_ids)
    for name in weights:
        if name not in commonness:
            raise ContextError(f"channel {name!r} has no commonness table")
    for name, table in commonness.items():
        if table.shape != (count,) or table.dtype != np.float32:
            raise ContextError(
                f"commonness table {name!r} must be float32 ({count},), got "
                f"{table.dtype} {table.shape}")
    return ScoringContext(
        index=index, gates=gates, render=render, outline=outline,
        weights=weights, commonness=commonness,
        scoring_config_hash=scoring_config_hash,
        commonness_config_hash=commonness_config_hash,
    )
