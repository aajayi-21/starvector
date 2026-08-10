"""Shared harness plumbing: wiring, paths, use accounting, records.

Spec: docs/specs/scoring-path.md sections 6, 14, and 15. The two
runners (v1, v2) share provider wiring, the artifact directory
layout, the U1 use deltas, and the committed harness record shape.
The records root is a parameter, thus tests write to scratch paths
and nothing lands in the repository without a deliberate run.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

from core.canonical import JsonValue, canonical_json, quantize_measured, sha256_hex
from core.types import (IntakeGates, PlacementConfig, PoolIndex, RenderParams,
                        StrokePath)
from pipeline.config import SUBMISSION_MODES, ScoringConfig
from pipeline.score import Encoders, encode_submissions
from pool.artifacts import write_json_pretty
from providers.protocols import (SketchEncoder, SketchPair, SketchPairSource,
                                 TextEncoder)

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


def text_encoder_hash(config: ScoringConfig) -> str:
    """The text_encoder slot hash, computed without wiring."""
    slot = config.providers.text_encoder
    if slot.provider == "openrouter":
        from providers.openrouter.embeddings import (EmbeddingSlotConfig,
                                                     embedding_config_hash)

        return embedding_config_hash(EmbeddingSlotConfig(
            slot="text_encoder",
            model=slot.model or config.providers.openrouter.default_model,
            dimension=slot.dimension or 0,
            encoding_format="float",
        ))
    from providers.fake.text_encoder import FakeTextEncoder

    return FakeTextEncoder(dimension=slot.dimension or 64).config_hash


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
        "text_encoder": hash_for(
            "text_encoder", lambda: text_encoder_hash(config)),
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


def wire_text_encoder(config: ScoringConfig, data_root: Path) -> TextEncoder:
    """Build the text encoder instance for this config."""
    import os

    slot = config.providers.text_encoder
    if slot.provider == "openrouter":
        from providers.openrouter.client import (OpenRouterClient,
                                                 OpenRouterClientConfig)
        from providers.openrouter.embeddings import (EmbeddingSlotConfig,
                                                     OpenRouterTextEncoder)

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
        return OpenRouterTextEncoder(
            EmbeddingSlotConfig(
                slot="text_encoder",
                model=slot.model or section.default_model,
                dimension=slot.dimension or 0,
                encoding_format="float",
            ),
            client,
            data_root / "cache" / "openrouter",
        )
    from providers.fake.text_encoder import FakeTextEncoder

    return FakeTextEncoder(dimension=slot.dimension or 64)


def wire_encoders(config: ScoringConfig, data_root: Path,
                  providers: Mapping[str, object] | None = None) -> Encoders:
    """The two Layer 2 slots, with injected instances used first."""
    providers = providers or {}
    sketch = providers.get("sketch_encoder") or wire_sketch_encoder(
        config, data_root)
    text = providers.get("text_encoder") or wire_text_encoder(
        config, data_root)
    return Encoders(sketch=sketch, text=text)   # type: ignore[arg-type]


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


def check_element_space(record_provider_hashes: Mapping[str, str],
                        slot_hashes: Mapping[str, str]) -> None:
    """Atom vectors and element vectors must share one space (R7).

    The p04 stage encoded the vocabulary with the preparation's
    text_encoder slot. The element channel compares atom vectors with
    those vectors, thus the scoring slot must be the same provider
    configuration. Two different encoders give cosines with no meaning,
    and the numbers look ordinary.
    """
    prepared = record_provider_hashes.get("text_encoder")
    if prepared != slot_hashes["text_encoder"]:
        raise ValueError(
            "the scoring text_encoder config_hash "
            f"{slot_hashes['text_encoder'][:8]} is not the preparation's "
            f"{str(prepared)[:8]} — the atom vectors and the element "
            "vectors would not share a space (R7)")


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


def submission_record(pair: SketchPair, mode: str) -> dict[str, JsonValue]:
    """The frozen wire record for one dataset pair (spec P3 section 11).

    The mode says which of the pair's payloads become a submission:
    sketch fills canvas_strokes, text fills pasted_text, and mixed
    fills the two. The mode is a harness concept and stops here — the
    scoring path reads the record and does not learn which mode built
    it (Rule 5). A payload the mode needs and the pair does not have
    raises: a silently thinner submission makes numbers that do not
    answer the question asked.
    """
    if mode not in SUBMISSION_MODES:
        raise ValueError(f"unknown submission mode: {mode!r}")
    strokes: tuple[StrokePath, ...] = ()
    if mode in ("sketch", "mixed"):
        if pair.sketch_strokes is None:
            raise ValueError(
                f"{pair.pair_key}: no vector strokes (D10 is not built)")
        strokes = pair.sketch_strokes
    text: str | None = None
    if mode in ("text", "mixed"):
        if pair.text is None:
            raise ValueError(
                f"{pair.pair_key}: the dataset gave no description")
        text = pair.text
    return {
        "impressions": [],
        "canvas_strokes": [
            {"points": [[x, y] for x, y in stroke], "group_id": None}
            for stroke in strokes
        ],
        "groups": [],
        "relations": [],
        "pasted_text": text,
    }


def check_selected_pairs(pairs: Mapping[str, SketchPair],
                         keys: list[str], gates, canvas_px: int,
                         mode: str) -> None:
    """Pre-flight: each selected pair must build and clear Layer 0.

    Runs before the encoder spend, and covers the background split
    too — a submission Layer 0 rejects cannot be a live submission,
    thus it must not shape a commonness table. A missing payload for
    the mode also fails here, which keeps the background set the
    same: each background submission activates the same channels,
    which is what a commonness table means (spec P3 section 10).
    Raises one aggregate error naming each failing pair, so the
    operator adjusts the config before the run costs anything.
    """
    from core.intake import IntakeError, validate_submission

    failures = []
    for key in keys:
        pair = pairs[key]
        try:
            validate_submission(submission_record(pair, mode), gates,
                                canvas_px)
        except (IntakeError, ValueError) as error:
            failures.append(f"{key}: {error}")
    if failures:
        raise ValueError(
            f"{len(failures)} selected pair(s) do not clear the Layer 0 "
            "gates — adjust the gates or the dataset before the run: "
            + "; ".join(failures))


def prewarm_records(records: Sequence[JsonValue], gates: IntakeGates,
                    render: RenderParams, encoders: Encoders) -> None:
    """Warm the provider caches for a trial loop in batched calls.

    The trial loop encodes one submission for each score_trial run,
    which turns each cold atom into one post of its own (the Phase 3
    accounting: 641 of 871 posts). One batched step here fills the
    caches, thus the loop runs warm. The result is discarded — an
    encode is deterministic and cached by content, so this step cannot
    change a score (P4 decision D12).
    """
    from core.intake import validate_submission

    submissions = [validate_submission(record, gates, render.canvas_px)
                   for record in records]
    encode_submissions(submissions, render, encoders)


def full_background(config: ScoringConfig, source: SketchPairSource,
                    mode: str, index: PoolIndex,
                    placement: PlacementConfig, data_root: Path,
                    generalizer: object | None = None,
                    ) -> list[tuple[str, JsonValue]]:
    """The full background: the dataset half plus the source B half.

    The dataset half draws background_count minus the synthetic count
    from the background split, thus the total stays background_count
    (D11). The rows come back sorted by key — synthetic keys hold
    their own prefix and cannot collide with pair keys.
    """
    from validation.splits import select_keys

    synthetic = config.commonness.synthetic
    dataset_count = config.commonness.background_count \
        - (synthetic.count if synthetic else 0)
    keys = pair_keys_of(source)
    background_keys = select_keys(
        keys, config.commonness.split_salt,
        config.commonness.split_fractions, "background", dataset_count)
    pairs = pairs_by_key(source, set(background_keys))
    rows = [(key, submission_record(pairs[key], mode))
            for key in background_keys]
    rows.extend(synthetic_background(config, index, placement, data_root,
                                     generalizer))
    rows.sort(key=lambda entry: entry[0])
    return rows


def synthetic_background(config: ScoringConfig, index: PoolIndex,
                         placement: PlacementConfig, data_root: Path,
                         generalizer: object | None = None,
                         ) -> list[tuple[str, JsonValue]]:
    """The source B half of the background, labels discarded (D11).

    Resolves the fit config the commonness section names and reads the
    stored generalization table. Without an injected generalizer the
    table build task must have run — a missing table stops here with
    the command to run, because the build is a deliberate owner step,
    not a side effect of a background assembly.
    """
    synthetic = config.commonness.synthetic
    if synthetic is None:
        return []
    from validation.fitconfig import load_fit_config
    from validation.generator import synthetic_set

    fit_config = load_fit_config(Path(synthetic.fit_config))
    table = _stored_table(index, fit_config, data_root, generalizer)
    rows = synthetic_set(index, fit_config, table, placement,
                         seed=synthetic.seed, count=synthetic.count)
    return [(row.key, row.record) for row in rows]


def _stored_table(index: PoolIndex, fit_config, data_root: Path,
                  generalizer: object | None) -> dict[str, str]:
    from validation.generalize import ensure_table

    entry_count = len(index.pool_frequency)
    try:
        return ensure_table(
            data_root=data_root,
            vocabulary=index.vocabulary[:entry_count],
            config=fit_config, clock=default_clock,
            generalizer=generalizer or _no_generalizer())
    except _TableMissing as error:
        raise ValueError(
            "the generalization table is not built — run "
            "`uv run python -m validation.generalize` first "
            f"({error})") from error


class _TableMissing(RuntimeError):
    """The stored generalization table is not on disk."""


def _no_generalizer():
    """A generalizer stub that refuses to build — warm reads only.

    The background assembly must not spend the table-build posts as
    a side effect: the build is a deliberate owner-run step.
    """
    class _Refuses:
        config_hash = "unused"

        def generalize(self, texts):
            raise _TableMissing(f"{len(texts)} entries need the build job")

    return _Refuses()


def resolved_generator_hash(config: ScoringConfig, index: PoolIndex,
                            data_root: Path,
                            generalizer: object | None = None,
                            ) -> str | None:
    """The generator identity for the commonness key (spec P4 §6).

    None when the config has no synthetic section. The identity covers
    the level table, the vocabulary content, and the stored table
    content, thus it needs the table on disk.
    """
    synthetic = config.commonness.synthetic
    if synthetic is None:
        return None
    from validation.fitconfig import load_fit_config
    from validation.generalize import table_hash, vocabulary_digest
    from validation.generator import generator_config_hash

    fit_config = load_fit_config(Path(synthetic.fit_config))
    entry_count = len(index.pool_frequency)
    vocabulary = index.vocabulary[:entry_count]
    table = _stored_table(index, fit_config, data_root, generalizer)
    return generator_config_hash(fit_config, vocabulary_digest(vocabulary),
                                 table_hash(table))


def record_label(harness: str, tag: str, harness_hash: str) -> str:
    return f"{harness}-{tag}-{harness_hash[:8]}"


def write_harness_record(records_root: Path, harness: str, tag: str,
                         harness_hash: str,
                         content: dict[str, JsonValue]) -> Path:
    """Write one harness record, pretty canonical JSON plus newline.

    A record with human-filled verdict fields is kept as-is — a
    re-run must not move a recorded decision back to pending. The kept
    record must name the same run identity: a stale record for a
    different preparation at the same path raises, it does not
    masquerade as this run's result.
    """
    import json

    path = records_root / f"{record_label(harness, tag, harness_hash)}.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("verdict") != VERDICT_TEMPLATE["verdict"]:
            for name in ("index_id", "preparation_version_id",
                         "scoring_config_hash"):
                if existing.get(name) != content.get(name):
                    raise ValueError(
                        f"{path}: a record with a filled verdict names a "
                        f"different {name} — move the old record aside "
                        "before this run writes its own")
            return path
    write_json_pretty(path, content)
    return path


def quantized(value: float) -> float:
    """Shortcut for measured values entering artifacts."""
    return quantize_measured(value)
