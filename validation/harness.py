"""Shared harness plumbing: wiring, paths, use accounting, records.

Spec: docs/specs/scoring-path.md sections 6, 14, and 15. The two
runners (v1, v2) share provider wiring, the artifact directory
layout, the U1 use deltas, and the committed harness record shape.
The records root is a parameter, thus tests write to scratch paths
and nothing lands in the repository without a deliberate run.
"""

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from core.canonical import JsonValue, canonical_json, quantize_measured, sha256_hex
from core.types import StrokePath
from pipeline.config import ScoringConfig
from pool.artifacts import write_json_pretty
from providers.protocols import SketchEncoder, SketchPair, SketchPairSource

# The s08-shape verdict fields, for the human to fill before commit.
VERDICT_TEMPLATE: dict[str, JsonValue] = {
    "verdict": "pending",
    "reviewer": "",
    "date": "",
    "notes": "",
}


def default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


class UsageDelta:
    """Duck-typed posts and cache-hit deltas around one span (U1)."""

    def __init__(self, provider: object) -> None:
        self._provider = provider
        self._posts = int(getattr(provider, "post_count", 0))
        self._hits = int(getattr(provider, "cache_hit_count", 0))

    @property
    def posts(self) -> int:
        return int(getattr(self._provider, "post_count", 0)) - self._posts

    @property
    def cache_hits(self) -> int:
        return int(getattr(self._provider, "cache_hit_count", 0)) - self._hits


def harness_config_hash(harness: str, scoring_config_hash: str) -> str:
    """One hash for each (harness, scoring config) pairing."""
    return sha256_hex(canonical_json({
        "harness": harness,
        "scoring_config_hash": scoring_config_hash,
    }))


def validation_dir(data_root: Path, harness: str, index_id: str,
                   harness_hash: str) -> Path:
    """The harness artifact directory (spec section 14)."""
    return data_root / "validation" / harness / index_id[:8] / harness_hash[:8]


def sketch_encoder_hash(config: ScoringConfig) -> str:
    """The sketch_encoder slot hash, computed without wiring."""
    slot = config.providers.sketch_encoder
    if slot.provider == "openrouter":
        from providers.openrouter.embeddings import (EmbeddingSlotConfig,
                                                     embedding_config_hash)

        return embedding_config_hash(EmbeddingSlotConfig(
            slot="sketch_encoder",
            model=slot.model or config.providers.openrouter.default_model,
            dimension=slot.dimension or 0,
            encoding_format="float",
        ))
    from providers.fake.sketch_encoder import FakeSketchEncoder

    return FakeSketchEncoder(dimension=slot.dimension or 64).config_hash


def sketch_pairs_hash(config: ScoringConfig) -> str:
    """The sketch_pairs slot hash, computed without wiring."""
    dataset = config.commonness.dataset
    if dataset.provider == "fscoco":
        from providers.sketchsets.fscoco import FSCocoConfig, fscoco_config_hash

        return fscoco_config_hash(FSCocoConfig(
            url=dataset.url or "",
            archive_sha256=dataset.archive_sha256,
            coordinate_extent=dataset.coordinate_extent,
            budget_bytes=dataset.budget_bytes or 0,
        ))
    from providers.sketchsets.fake import (FakeSketchPairSource,
                                           FakeSketchsetConfig)

    return FakeSketchPairSource(FakeSketchsetConfig(
        pair_count=dataset.fake_pair_count or 1,
        neardup_families=dataset.fake_neardup_families or (),
    )).config_hash


def scoring_provider_hashes(
    config: ScoringConfig, providers: Mapping[str, object] | None = None
) -> dict[str, str]:
    """The two slot hashes that enter scoring_config_hash.

    An injected provider instance (tests) supplies its own hash.
    """
    providers = providers or {}

    def hash_for(slot_name: str, fallback: Callable[[], str]) -> str:
        provider = providers.get(slot_name)
        if provider is not None:
            return str(getattr(provider, "config_hash"))
        return fallback()

    return {
        "sketch_encoder": hash_for(
            "sketch_encoder", lambda: sketch_encoder_hash(config)),
        "sketch_pairs": hash_for(
            "sketch_pairs", lambda: sketch_pairs_hash(config)),
    }


def wire_sketch_encoder(config: ScoringConfig,
                        data_root: Path) -> SketchEncoder:
    """Build the sketch encoder instance for this config."""
    import os

    slot = config.providers.sketch_encoder
    if slot.provider == "openrouter":
        from providers.openrouter.client import (OpenRouterClient,
                                                 OpenRouterClientConfig)
        from providers.openrouter.embeddings import (EmbeddingSlotConfig,
                                                     OpenRouterImageEncoder)

        section = config.providers.openrouter
        client = OpenRouterClient(
            OpenRouterClientConfig(
                max_concurrency=section.max_concurrency,
                requests_per_second=section.requests_per_second,
                timeout_seconds=section.timeout_seconds,
                retry_limit=section.retry_limit,
            ),
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        )
        return OpenRouterImageEncoder(
            EmbeddingSlotConfig(
                slot="sketch_encoder",
                model=slot.model or section.default_model,
                dimension=slot.dimension or 0,
                encoding_format="float",
            ),
            client,
            data_root / "cache" / "openrouter",
        )
    from providers.fake.sketch_encoder import FakeSketchEncoder

    return FakeSketchEncoder(dimension=slot.dimension or 64)


def wire_sketch_pairs(config: ScoringConfig,
                      data_root: Path) -> SketchPairSource:
    """Build the sketch-pair source instance for this config."""
    dataset = config.commonness.dataset
    if dataset.provider == "fscoco":
        from providers.sketchsets.fscoco import (FSCocoConfig,
                                                 FSCocoSketchPairSource)

        return FSCocoSketchPairSource(
            FSCocoConfig(
                url=dataset.url or "",
                archive_sha256=dataset.archive_sha256,
                coordinate_extent=dataset.coordinate_extent,
                budget_bytes=dataset.budget_bytes or 0,
            ),
            data_root,
        )
    from providers.sketchsets.fake import (FakeSketchPairSource,
                                           FakeSketchsetConfig)

    return FakeSketchPairSource(FakeSketchsetConfig(
        pair_count=dataset.fake_pair_count or 1,
        neardup_families=dataset.fake_neardup_families or (),
    ))


def pair_keys_of(source: SketchPairSource) -> list[str]:
    """First walk: the pair keys alone, payloads dropped."""
    return [pair.pair_key for pair in source.iter_pairs()]


def pairs_by_key(source: SketchPairSource,
                 wanted: set[str]) -> dict[str, SketchPair]:
    """Second walk: the selected pairs, keyed."""
    selected = {pair.pair_key: pair for pair in source.iter_pairs()
                if pair.pair_key in wanted}
    missing = sorted(wanted - set(selected))
    if missing:
        raise ValueError(f"dataset did not yield selected pairs: {missing}")
    return selected


def submission_record_from_strokes(
        strokes: tuple[StrokePath, ...]) -> dict[str, JsonValue]:
    """The frozen wire record for one dataset sketch (spec section 12)."""
    return {
        "impressions": [],
        "canvas_strokes": [
            {"points": [[x, y] for x, y in stroke], "group_id": None}
            for stroke in strokes
        ],
        "groups": [],
        "relations": [],
        "pasted_text": None,
    }


def record_label(harness: str, tag: str, harness_hash: str) -> str:
    return f"{harness}-{tag}-{harness_hash[:8]}"


def write_harness_record(records_root: Path, harness: str, tag: str,
                         harness_hash: str,
                         content: dict[str, JsonValue]) -> Path:
    """Write one harness record, pretty canonical JSON plus newline."""
    path = records_root / f"{record_label(harness, tag, harness_hash)}.json"
    write_json_pretty(path, content)
    return path


def quantized(value: float) -> float:
    """Shortcut for measured values entering artifacts."""
    return quantize_measured(value)
