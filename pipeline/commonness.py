"""The commonness table: a keyed artifact built from the background set.

Spec: docs/specs/scoring-path.md sections 11 and 14. The table answers,
for each pool image, how high it scores against a typical submission
(architecture section 13.2) — in this phase from source A only: human
sketches from the dataset's background split (D6). The artifact is
written one time at its key. The index and the encoder come as
arguments, thus the V1 harness reuses the task with its union index
(D7). The background comes as a thunk: a warm run reads the artifact
and does not touch the dataset or the network (U1).
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.channels.outline import outline_scores
from core.intake import render_strokes
from core.types import OutlineConfig, PoolIndex, PoolScores, RenderParams
from pipeline.config import ScoringConfig
from pool.artifacts import ManifestError, write_json_pretty
from pool.preparation.manifest import save_npy_atomic
from providers.protocols import SketchEncoder, SketchPair

_ENCODE_BATCH = 64

_TABLE_FILE = "outline.npy"
_META_FILE = "meta.json"


class CommonnessResult(NamedTuple):
    """One table plus the U1 accounting for the run that made it."""

    table: PoolScores
    posts: int
    cache_hits: int
    reused: bool


def commonness_config_hash(config: ScoringConfig, render: RenderParams,
                           sketch_encoder_hash: str,
                           dataset_config_hash: str) -> str:
    """The artifact key half that names the table's determinants.

    Covers the dataset identity, the split salt and background range,
    the background count, the encoder, the render values, and the
    channel config (spec section 6). The v1 and v2 fractions are not
    in the key: the background range is [0, background), and the
    other fractions cannot move its membership (D8).
    """
    return sha256_hex(canonical_json({
        "dataset_config_hash": dataset_config_hash,
        "split_salt": config.commonness.split_salt,
        "background_fraction": config.commonness.split_fractions.background,
        "background_count": config.commonness.background_count,
        "sketch_encoder_config_hash": sketch_encoder_hash,
        "render": {"canvas_px": render.canvas_px,
                   "line_width_px": render.line_width_px},
        "channel": {"outline": {
            "comparison_rule": config.channels.outline.comparison_rule}},
    }))


def commonness_dir(data_root: Path, index_id: str,
                   commonness_hash: str) -> Path:
    """The artifact directory (spec section 14)."""
    return data_root / "commonness" / index_id[:8] / commonness_hash[:8]


def build_commonness_table(index: PoolIndex,
                           background: Sequence[SketchPair],
                           render: RenderParams, outline: OutlineConfig,
                           encoder: SketchEncoder) -> PoolScores:
    """The mean raw outline score across the background set.

    commonness[x] = mean across background sketches of the raw
    channel score for image x (architecture section 13.2) — before
    correction and before standardizing. Shape (N,), float32. The
    background must come in ascending pair_key sequence with vector
    strokes on each pair (D10) — a raster-only pair raises with the
    pair named.
    """
    if not background:
        raise ValueError("the background set is empty")
    keys = [pair.pair_key for pair in background]
    if any(keys[i] >= keys[i + 1] for i in range(len(keys) - 1)):
        raise ValueError("background pairs must be ascending by pair_key")
    total = np.zeros(len(index.image_ids), dtype=np.float64)   # (N,)
    for start in range(0, len(background), _ENCODE_BATCH):
        chunk = background[start:start + _ENCODE_BATCH]
        for pair in chunk:
            if pair.sketch_strokes is None:
                raise ValueError(
                    f"{pair.pair_key}: no vector strokes — D10 is not built")
        renders = [render_strokes(pair.sketch_strokes, render.canvas_px,
                                  render.line_width_px)
                   for pair in chunk]
        vectors = encoder.encode_images(renders)               # (B, d)
        for row in vectors:
            total += outline_scores(row, index, outline).astype(np.float64)
    return (total / len(background)).astype(np.float32)        # (N,)


def ensure_commonness_table(
    *, data_root: Path, index: PoolIndex, commonness_hash: str,
    background: Callable[[], Sequence[SketchPair]],
    render: RenderParams, outline: OutlineConfig, encoder: SketchEncoder,
    clock: Callable[[], str],
) -> CommonnessResult:
    """Read the table at its key, or build and store it one time.

    Written one time: a complete artifact (a parseable meta.json) is
    read back with no dataset access and no encoder use. On a build, the
    array is written first and meta.json last — meta is the
    completeness marker, the P1b resume rule. The meta file carries
    the U1 totals and is out of the byte-determinism scope (spec
    section 17).
    """
    directory = commonness_dir(data_root, index.index_id, commonness_hash)
    table_path = directory / _TABLE_FILE
    meta_path = directory / _META_FILE
    count = len(index.image_ids)
    if meta_path.is_file():
        try:
            import json
            json.loads(meta_path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise ManifestError(
                f"{meta_path}: complete marker does not parse: {error}. "
                "Delete the directory to compute it again.") from error
        table = np.load(table_path)
        if table.shape != (count,) or table.dtype != np.float32:
            raise ManifestError(
                f"{table_path}: expected float32 ({count},), got "
                f"{table.dtype} {table.shape}")
        return CommonnessResult(table=table, posts=0, cache_hits=0,
                                reused=True)

    posts_before = int(getattr(encoder, "post_count", 0))
    hits_before = int(getattr(encoder, "cache_hit_count", 0))
    pairs = background()
    table = build_commonness_table(index, pairs, render, outline, encoder)
    posts = int(getattr(encoder, "post_count", 0)) - posts_before
    cache_hits = int(getattr(encoder, "cache_hit_count", 0)) - hits_before

    save_npy_atomic(table_path, table)
    meta: dict[str, JsonValue] = {
        "index_id": index.index_id,
        "commonness_config_hash": commonness_hash,
        "background_count": len(pairs),
        "pool_image_count": count,
        "array_shapes": {"outline": [count]},
        "provider_posts": posts,
        "provider_cache_hits": cache_hits,
        "created_at": clock(),
    }
    write_json_pretty(meta_path, meta)
    return CommonnessResult(table=table, posts=posts, cache_hits=cache_hits,
                            reused=False)
