"""The commonness tables: keyed artifacts built from the background set.

Spec: docs/specs/scoring-path.md sections 11 and 14, extended by
docs/specs/element-channel.md section 10 (D11) and
docs/specs/fuse-and-validate.md sections 12 and 13. A table answers,
for each pool image, how high it scores against a typical submission
(architecture section 13.2). The background is source A (dataset
submissions) plus, when the config says so, source B (synthetic
submissions from the generator, labels discarded). One table is
written for each built channel the background activates, at one
shared key. Each channel's table is the mean across the background
submissions that activate that channel (P4 decision D13) — a mixed
background activates different channels with different subsets, and
the contributor counts go into the meta file. The artifacts are
written one time. The index and the encoders come as arguments, thus
the V1 harness reuses the task with its union index (D7). The
background comes as a thunk: a warm run reads the artifacts and does
not touch the dataset or the network (U1).
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.fusion import active_channels
from core.intake import validate_submission
from core.types import (ROUTING_TABLE, ChannelName, ElementConfig, IntakeGates,
                        OutlineConfig, PlacementConfig, PoolIndex, PoolScores,
                        RenderParams)
from pipeline.config import ScoringConfig, config_to_json_value
from pipeline.score import Encoders, channel_scores, encode_submissions
from pool.artifacts import ManifestError, write_json_pretty
from pool.preparation.manifest import save_npy_atomic

# How many background submissions are encoded together. This limits
# the memory the vectors hold while keeping the provider batches full.
_SUBMISSION_BATCH = 64

_META_FILE = "meta.json"


class CommonnessResult(NamedTuple):
    """The tables plus the U1 accounting for the run that made them.

    posts and cache_hits are the totals across the Layer 2 slots. The
    harness reports the slots one by one from its own deltas.
    contributors holds, for each built channel, how many background
    submissions its mean ranges across (D13).
    """

    tables: Mapping[ChannelName, PoolScores]
    contributors: Mapping[ChannelName, int]
    posts: int
    cache_hits: int
    reused: bool


class BuiltTables(NamedTuple):
    """One cold build: the tables and their contributor counts."""

    tables: dict[ChannelName, PoolScores]
    contributors: dict[ChannelName, int]


def table_file(channel: ChannelName) -> str:
    """The artifact file name of one channel's table (D11)."""
    return f"{channel}.npy"


def commonness_config_hash(config: ScoringConfig, render: RenderParams,
                           sketch_encoder_hash: str, text_encoder_hash: str,
                           dataset_config_hash: str,
                           generator_hash: str | None = None) -> str:
    """The artifact key half that names the tables' determinants.

    Covers the dataset identity, the split salt and background range,
    the background count, the submission mode, the two Layer 2 slots,
    the render values, the intake gates (the pre-flight shapes the
    background — P4 decision D12), the full channels config, and the
    source B identity when the config asks for one (spec P4 section
    12). The v1 and v2 fractions are not in the key: the background
    range is [0, background), and the other fractions cannot move its
    membership (D8).
    """
    synthetic = config.commonness.synthetic
    if (synthetic is None) != (generator_hash is None):
        raise ValueError(
            "generator_hash must be given when commonness.synthetic is set, "
            "and must be None when it is not")
    document: dict[str, JsonValue] = {
        "dataset_config_hash": dataset_config_hash,
        "split_salt": config.commonness.split_salt,
        "background_fraction": config.commonness.split_fractions.background,
        "background_count": config.commonness.background_count,
        "submission_mode": config.validation.submission_mode,
        "sketch_encoder_config_hash": sketch_encoder_hash,
        "text_encoder_config_hash": text_encoder_hash,
        "render": {"canvas_px": render.canvas_px,
                   "line_width_px": render.line_width_px},
        "intake": config_to_json_value(config)["intake"],
        "channels": config_to_json_value(config)["channels"],
        "synthetic": (None if synthetic is None else {
            "generator_config_hash": generator_hash,
            "count": synthetic.count,
            "seed": synthetic.seed,
        }),
    }
    return sha256_hex(canonical_json(document))


def commonness_dir(data_root: Path, index_id: str,
                   commonness_hash: str) -> Path:
    """The artifact directory (spec section 14)."""
    return data_root / "commonness" / index_id[:8] / commonness_hash[:8]


def build_commonness_tables(
    index: PoolIndex, background: Sequence[tuple[str, JsonValue]], *,
    gates: IntakeGates, render: RenderParams, outline: OutlineConfig,
    element: ElementConfig, placement: PlacementConfig,
    encoders: Encoders,
) -> BuiltTables:
    """The mean raw channel score across the activating background.

    commonness[channel][x] = mean across the background submissions
    that activate the channel of the raw channel score for image x
    (architecture section 13.2, P4 decision D13) — before correction
    and before standardizing. Each table has shape (N,), float32.

    A mixed background activates different channels with different
    subsets — the dataset half holds no RELATION atoms and the
    synthetic half does — thus the mean of each channel ranges across
    its own activating subset, and the contributor counts are part of
    the output and the meta file. A channel no background submission
    activates gets no table. Phase 3's rule, that a background which
    activates a channel in part is an error, applied to backgrounds of
    one mode, and D13 amends it.

    background holds (pair key, wire record) rows in ascending key
    sequence, thus the sum is made in a fixed sequence and two runs
    give equal bytes. The records are built before this task starts,
    so it knows nothing about modes, datasets, or generators.

    The content is a pure function of the background and the index —
    the caller's weight table cannot shape it (D12, ruling
    2026-08-10). Two runners with different weight tables then read
    equal bytes at one key, and the context selects the weighted
    subset.
    """
    if not background:
        raise ValueError("the background set is empty")
    keys = [key for key, _ in background]
    if any(keys[i] >= keys[i + 1] for i in range(len(keys) - 1)):
        raise ValueError("background records must be ascending by pair_key")
    count = len(index.image_ids)
    totals: dict[ChannelName, np.ndarray] = {}
    contributors: dict[ChannelName, int] = {}

    for start in range(0, len(background), _SUBMISSION_BATCH):
        chunk = background[start:start + _SUBMISSION_BATCH]
        submissions = [validate_submission(record, gates, render.canvas_px)
                       for _, record in chunk]
        encoded = encode_submissions(submissions, render, encoders)
        for row in encoded:
            for name in sorted(active_channels(row, ROUTING_TABLE)):
                scores = channel_scores(name, row, index, outline, element,
                                        placement)
                if name not in totals:
                    totals[name] = np.zeros(count, dtype=np.float64)
                    contributors[name] = 0
                totals[name] += scores.astype(np.float64)
                contributors[name] += 1

    tables = {name: (total / contributors[name]).astype(np.float32)
              for name, total in totals.items()}
    return BuiltTables(tables=tables, contributors=contributors)


def _provider_counter(encoders: Encoders, name: str) -> int:
    """The summed U1 counter across the Layer 2 slots."""
    return sum(int(getattr(slot, name, 0)) for slot in encoders)


def _read_tables(directory: Path, channels: Sequence[ChannelName],
                 count: int) -> dict[ChannelName, PoolScores]:
    """Read back the stored tables named by the meta file."""
    tables: dict[ChannelName, PoolScores] = {}
    for name in channels:
        path = directory / table_file(name)
        table = np.load(path)
        if table.shape != (count,) or table.dtype != np.float32:
            raise ManifestError(
                f"{path}: expected float32 ({count},), got "
                f"{table.dtype} {table.shape}")
        if not np.isfinite(table).all():
            raise ManifestError(
                f"{path}: the stored table holds a non-finite value")
        tables[name] = table
    return tables


def ensure_commonness_tables(
    *, data_root: Path, index: PoolIndex, commonness_hash: str,
    background: Callable[[], Sequence[tuple[str, JsonValue]]],
    gates: IntakeGates, render: RenderParams, outline: OutlineConfig,
    element: ElementConfig, placement: PlacementConfig,
    encoders: Encoders,
    submission_mode: str, clock: Callable[[], str],
    required_channels: Sequence[ChannelName] = (),
) -> CommonnessResult:
    """Read the tables at their key, or build and store them one time.

    Written one time: a complete artifact (a parseable meta.json) is
    read back with no dataset access and no encoder use. On a build,
    the arrays are written first and meta.json last — meta is the
    completeness marker, the P1b resume rule. The meta file carries the
    U1 totals and is out of the byte-determinism scope (spec section
    17).

    required_channels names the channels the caller's trials activate:
    a required channel with no table stops the run here, and not after
    a trial spends a post on a path that raises (D13).
    """
    directory = commonness_dir(data_root, index.index_id, commonness_hash)
    meta_path = directory / _META_FILE
    count = len(index.image_ids)

    def checked_required(built: Mapping[ChannelName, PoolScores]) -> None:
        missing = sorted(set(required_channels) - set(built))
        if missing:
            raise ValueError(
                f"no background submission activates {missing} and the "
                "run's trials read those channels — the background "
                "composition cannot support this configuration (D13)")

    if meta_path.is_file():
        try:
            import json
            meta_read = json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise ManifestError(
                f"{meta_path}: complete marker does not parse: {error}. "
                "Delete the directory to compute it again.") from error
        # The directory key truncates the two identities — the meta
        # carries them in full, and a read-back must agree.
        for name, expected in (("index_id", index.index_id),
                               ("commonness_config_hash", commonness_hash)):
            if meta_read.get(name) != expected:
                raise ManifestError(
                    f"{meta_path}: {name} does not agree with the "
                    "requested table — a truncated-key collision")
        stored = meta_read.get("channels")
        if not isinstance(stored, list) or not all(
                isinstance(name, str) for name in stored):
            raise ManifestError(
                f"{meta_path}: the channels field is not a list of names")
        stored_contributors = meta_read.get("contributors")
        if not isinstance(stored_contributors, dict):
            raise ManifestError(
                f"{meta_path}: the contributors field is not an object")
        tables = _read_tables(directory, stored, count)
        checked_required(tables)
        return CommonnessResult(
            tables=tables,
            contributors={str(k): int(v)
                          for k, v in stored_contributors.items()},
            posts=0, cache_hits=0, reused=True)

    posts_before = _provider_counter(encoders, "post_count")
    hits_before = _provider_counter(encoders, "cache_hit_count")
    records = background()
    built = build_commonness_tables(
        index, records, gates=gates, render=render, outline=outline,
        element=element, placement=placement, encoders=encoders)
    tables = built.tables
    if not tables:
        raise ValueError(
            "the background set activates no built channel — nothing to "
            "correct with")
    checked_required(tables)
    for name, table in tables.items():
        if not np.isfinite(table).all():
            raise ValueError(
                f"the built {name} commonness table holds a non-finite "
                "value — the encoder gave a bad vector")
    posts = _provider_counter(encoders, "post_count") - posts_before
    cache_hits = _provider_counter(encoders, "cache_hit_count") - hits_before

    names = sorted(tables)
    for name in names:
        save_npy_atomic(directory / table_file(name), tables[name])
    meta: dict[str, JsonValue] = {
        "index_id": index.index_id,
        "commonness_config_hash": commonness_hash,
        "submission_mode": submission_mode,
        "background_count": len(records),
        "pool_image_count": count,
        "channels": names,
        "contributors": {name: built.contributors[name] for name in names},
        "array_shapes": {name: [count] for name in names},
        "provider_posts": posts,
        "provider_cache_hits": cache_hits,
        "created_at": clock(),
    }
    write_json_pretty(meta_path, meta)
    return CommonnessResult(tables=tables, contributors=built.contributors,
                            posts=posts, cache_hits=cache_hits, reused=False)
