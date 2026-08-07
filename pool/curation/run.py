"""The imperative shell of the curation pipeline.

Spec: docs/specs/pool-curation.md sections 10 and 12. This module wires
providers from configuration, sequences stages s00 through s09, resumes
from complete stage directories, enforces the extraction budget (U1),
and holds the s08 human review gate. Stage logic itself is pure and
lives in pool/curation/stages/.
"""

import datetime as _datetime
import os
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from core.canonical import JsonValue, canonical_json, quantize_measured, sha256_hex
from pool.curation import manifest as mf
from pool.curation.config import (
    CurationConfig,
    SlotSection,
    curation_config_hash,
)
from pool.curation.stages import (
    classify,
    diversity,
    materialize,
    neardup,
    objectsize,
    release,
    review,
    screen,
    snapshot,
    text,
)
from pool.curation.types import (
    STAGE_NAMES,
    ArtifactTree,
    CandidateRecord,
    ImageRecord,
    Rejection,
    RunReport,
    StageMeta,
    StageReport,
)
from providers.protocols import (
    ImageEncoder,
    MaterializedImage,
    SalientObjectEstimator,
    SourceCorpus,
    SourceRecord,
    TextCoverageEstimator,
    ZeroShotImageClassifier,
)

# Shell-only constant: how many survivor images are decoded into memory
# at one time. This limits memory use and cannot change results.
_BYTE_SLICE = 256


class GateHalt(Exception):
    """Internal control flow for the s08 review gate. Not user-facing."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _slot_hash(slot_name: str, slot: SlotSection, config: CurationConfig) -> str:
    """The config hash of one slot, computable with no client and no key."""
    if slot.provider == "openrouter":
        from providers.openrouter import slots as orslots

        return orslots.slot_config_hash(_openrouter_slot_config(slot_name, slot, config))
    if slot.provider == "fake":
        if slot_name == "encoder":
            from providers.fake.encoder import FakeImageEncoder

            return FakeImageEncoder(dimension=slot.dimension or 64).config_hash
        return sha256_hex(canonical_json({"provider": f"fake-{_fake_marker(slot_name)}"}))
    raise ValueError(f"unknown provider for slot {slot_name}: {slot.provider}")


def _fake_marker(slot_name: str) -> str:
    return {
        "text_coverage": "text-coverage",
        "classifier": "classifier",
        "object_size": "object-fraction",
    }[slot_name]


def _openrouter_slot_config(slot_name: str, slot: SlotSection, config: CurationConfig):
    from providers.openrouter import slots as orslots

    return orslots.OpenRouterSlotConfig(
        slot=slot_name,
        model=slot.model or config.providers.openrouter.default_model,
        template=slot.instruction_template or "",
        temperature=orslots.TEMPERATURE,
        seed=orslots.SEED,
        max_tokens=orslots.MAX_TOKENS,
        reasoning_enabled=orslots.REASONING_ENABLED,
        response_format_mode=config.providers.openrouter.response_format_mode,
        probability_sum_tolerance=slot.probability_sum_tolerance,
    )


def provider_config_hashes(config: CurationConfig, corpus: SourceCorpus) -> dict[str, str]:
    """The five hashes that enter curation_config_hash."""
    p = config.providers
    return {
        "corpus": corpus.config_hash,
        "text_coverage": _slot_hash("text_coverage", p.text_coverage, config),
        "classifier": _slot_hash("classifier", p.classifier, config),
        "object_size": _slot_hash("object_size", p.object_size, config),
        "encoder": _slot_hash("encoder", p.encoder, config),
    }


def wire_corpus(config: CurationConfig) -> SourceCorpus:
    """Build the corpus adapter the configuration names."""
    corpus = config.corpus
    if corpus.provider == "huggingface":
        from providers.corpora.huggingface import (
            HuggingFaceColumns,
            HuggingFaceCorpus,
            HuggingFaceCorpusConfig,
        )
        from providers.corpora.wikimedia import WikimediaFetchConfig

        m = corpus.materialization
        return HuggingFaceCorpus(
            HuggingFaceCorpusConfig(
                repo_id=corpus.repo_id,
                revision=corpus.revision,
                config_name=corpus.config_name,
                split=corpus.split,
                columns=HuggingFaceColumns(
                    source_key=corpus.columns.source_key,
                    claimed_width=corpus.columns.claimed_width,
                    claimed_height=corpus.columns.claimed_height,
                    captions=corpus.columns.captions,
                    attribution=corpus.columns.attribution,
                ),
                license_note=corpus.license_note,
                max_scan_shards=corpus.max_scan_shards,
                fetch=WikimediaFetchConfig(
                    thumbnail_width=m.thumbnail_width,
                    user_agent=m.user_agent,
                    max_concurrency=m.max_concurrency,
                    timeout_seconds=m.timeout_seconds,
                    retry_limit=m.retry_limit,
                    max_fetch_bytes=m.max_fetch_bytes,
                ),
            )
        )
    raise ValueError(
        f"corpus provider {corpus.provider!r} has no wiring here - "
        "inject a corpus instance for tests and fakes"
    )


def _wire_slot(slot_name: str, config: CurationConfig, data_root: Path):
    """Build one model provider instance right before its stage runs."""
    slot = getattr(config.providers, slot_name)
    if slot.provider == "fake":
        if slot_name == "encoder":
            from providers.fake.encoder import FakeImageEncoder

            return FakeImageEncoder(dimension=slot.dimension or 64)
        if slot_name == "text_coverage":
            from providers.fake.estimators import FakeTextCoverageEstimator

            return FakeTextCoverageEstimator()
        if slot_name == "classifier":
            from providers.fake.classifier import FakeZeroShotImageClassifier

            return FakeZeroShotImageClassifier()
        from providers.fake.estimators import FakeSalientObjectEstimator

        return FakeSalientObjectEstimator()
    if slot.provider == "openrouter":
        from providers.openrouter.client import OpenRouterClient, OpenRouterClientConfig

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        section = config.providers.openrouter
        client = OpenRouterClient(
            OpenRouterClientConfig(
                base_url="https://openrouter.ai/api/v1",
                max_concurrency=section.max_concurrency,
                requests_per_second=section.requests_per_second,
                timeout_seconds=section.timeout_seconds,
                retry_limit=section.retry_limit,
            ),
            api_key=api_key,
        )
        from providers.openrouter import slots as orslots

        slot_config = _openrouter_slot_config(slot_name, slot, config)
        cache_root = data_root / "cache" / "openrouter"
        cls = {
            "text_coverage": orslots.OpenRouterTextCoverageEstimator,
            "classifier": orslots.OpenRouterZeroShotImageClassifier,
            "object_size": orslots.OpenRouterSalientObjectEstimator,
        }[slot_name]
        return cls(slot_config, client, cache_root)
    raise ValueError(f"unknown provider for slot {slot_name}: {slot.provider}")


def _attribution_pairs(attribution: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in attribution.items()))


def _candidate_to_source(candidate: CandidateRecord) -> SourceRecord:
    return SourceRecord(
        source_key=candidate.source_key,
        claimed_width=candidate.claimed_width,
        claimed_height=candidate.claimed_height,
        captions=candidate.captions,
        attribution={k: v for k, v in candidate.attribution},
    )


def _rejection_counts(rejections: Sequence[Rejection]) -> tuple[tuple[str, int], ...]:
    counts = Counter(r.reason for r in rejections)
    return tuple(sorted(counts.items()))


def _meta(
    tree: ArtifactTree,
    stage: str,
    parent: str | None,
    input_count: int,
    survivors: int,
    rejections: Sequence[Rejection],
    config_echo: Mapping[str, JsonValue],
    provider_hashes: Mapping[str, str],
    counters: Mapping[str, int],
    bytes_retrieved: int,
    bytes_cumulative: int,
    provider_requests: int,
    code_version: str,
) -> StageMeta:
    return StageMeta(
        stage=stage,
        label=mf.stage_label(tree, stage),
        parent_stage=parent,
        input_count=input_count,
        survivor_count=survivors,
        rejection_count=len(rejections),
        rejections_by_reason=_rejection_counts(rejections),
        config_echo=tuple(sorted(config_echo.items())),
        provider_config_hashes=tuple(sorted((k, v) for k, v in provider_hashes.items())),
        counters=tuple(sorted(counters.items())),
        bytes_retrieved=bytes_retrieved,
        bytes_cumulative=bytes_cumulative,
        provider_requests=provider_requests,
        code_version=code_version,
    )


def _write_stage(
    tree: ArtifactTree,
    stage: str,
    meta: StageMeta,
    manifest_rows: Sequence[dict[str, JsonValue]],
    rejections: Sequence[Rejection],
) -> None:
    """Write a stage directory: rows and rejections first, meta last."""
    directory = mf.stage_dir(tree, stage)
    directory.mkdir(parents=True, exist_ok=True)
    mf.write_jsonl(directory / "manifest.jsonl", manifest_rows)
    mf.write_jsonl(directory / "rejections.jsonl", (mf.rejection_to_row(r) for r in rejections))
    mf.write_meta(tree, stage, meta)


def _read_parent_manifest(tree: ArtifactTree, parent: str) -> list[dict[str, JsonValue]]:
    return mf.read_jsonl(mf.stage_dir(tree, parent) / "manifest.jsonl")


def _read_records(tree: ArtifactTree) -> dict[str, ImageRecord]:
    rows = mf.read_jsonl(mf.stage_dir(tree, "s02-materialize") / "records.jsonl")
    records = (mf.row_to_image_record(row) for row in rows)
    return {record.image_id: record for record in records}


def _load_bytes(data_root: Path, image_ids: Sequence[str]) -> list[bytes]:
    return [mf.load_image_bytes(data_root, image_id) for image_id in image_ids]


def _cumulative(tree: ArtifactTree, parent: str | None) -> int:
    if parent is None:
        return 0
    return mf.read_meta(tree, parent).bytes_cumulative


# --- stage runners ---------------------------------------------------------


def run_s00_snapshot(
    corpus: SourceCorpus, config: CurationConfig, tree: ArtifactTree, code_version: str
) -> StageMeta:
    start_bytes = corpus.bytes_retrieved
    kept: list[CandidateRecord] = []
    enumerated = 0
    for record in corpus.iter_records():
        enumerated += 1
        if snapshot.keep_in_sample(
            config.sampling.sample_salt, record.source_key, config.sampling.sample_rate
        ):
            kept.append(
                CandidateRecord(
                    source_key=record.source_key,
                    claimed_width=record.claimed_width,
                    claimed_height=record.claimed_height,
                    captions=record.captions,
                    attribution=_attribution_pairs(record.attribution),
                )
            )
    kept.sort(key=lambda c: c.source_key)
    scan_bytes = corpus.bytes_retrieved - start_bytes
    meta = _meta(
        tree,
        "s00-snapshot",
        None,
        input_count=len(kept),
        survivors=len(kept),
        rejections=(),
        config_echo={
            "sample_salt": config.sampling.sample_salt,
            "sample_rate": config.sampling.sample_rate,
        },
        provider_hashes={"corpus": corpus.config_hash},
        counters={
            "enumerated": enumerated,
            "sampled_out": enumerated - len(kept),
            "scan_bytes": scan_bytes,
        },
        bytes_retrieved=scan_bytes,
        bytes_cumulative=scan_bytes,
        provider_requests=0,
        code_version=code_version,
    )
    _write_stage(tree, "s00-snapshot", meta, [mf.candidate_to_row(c) for c in kept], ())
    return meta


def run_s01_screen(config: CurationConfig, tree: ArtifactTree, code_version: str) -> StageMeta:
    rows = _read_parent_manifest(tree, "s00-snapshot")
    candidates = [mf.row_to_candidate(row) for row in rows]
    result = screen.screen_decisions(candidates, config.screen)
    survivors = sorted(result.survivors, key=lambda c: c.source_key)
    meta = _meta(
        tree,
        "s01-screen",
        "s00-snapshot",
        input_count=len(candidates),
        survivors=len(survivors),
        rejections=result.rejections,
        config_echo={
            "min_short_side": config.screen.min_short_side,
            "min_aspect": config.screen.min_aspect,
            "max_aspect": config.screen.max_aspect,
        },
        provider_hashes={},
        counters={},
        bytes_retrieved=0,
        bytes_cumulative=_cumulative(tree, "s00-snapshot"),
        provider_requests=0,
        code_version=code_version,
    )
    _write_stage(
        tree, "s01-screen", meta, [mf.candidate_to_row(c) for c in survivors], result.rejections
    )
    return meta


def run_s02_materialize(
    corpus: SourceCorpus, config: CurationConfig, tree: ArtifactTree, code_version: str
) -> StageMeta:
    stage = "s02-materialize"
    rows = _read_parent_manifest(tree, "s01-screen")
    candidates = {c.source_key: c for c in (mf.row_to_candidate(row) for row in rows)}
    order = snapshot.fetch_order(candidates.keys(), config.sampling.sample_salt)

    scan_bytes = dict(mf.read_meta(tree, "s00-snapshot").counters).get("scan_bytes", 0)
    budget = config.extraction.budget_bytes
    cap = config.extraction.materialize_cap
    batch_size = config.corpus.materialization.fetch_batch_size
    transport_start = corpus.bytes_retrieved

    decision_bytes = int(scan_bytes)
    fetched = 0
    budget_stopped = 0
    rejections: list[Rejection] = []
    admitted: list[tuple[str, str, bytes]] = []  # (source_key, image_id, bytes)
    position = 0

    while position < len(order):
        if decision_bytes >= budget or (cap is not None and fetched >= cap):
            budget_stopped = 1
            break
        batch_keys = order[position : position + batch_size]
        position += len(batch_keys)
        batch = [_candidate_to_source(candidates[k]) for k in batch_keys]
        results = corpus.materialize_many(batch)
        if len(results) != len(batch):
            raise mf.ManifestError("materialize_many result is not aligned with its input")
        for key, outcome in zip(batch_keys, results):
            if isinstance(outcome, MaterializedImage):
                fetched += 1
                decision_bytes += len(outcome.image_bytes)
                image_id = mf.store_image_bytes(tree.data_root, outcome.image_bytes)
                admitted.append((key, image_id, outcome.image_bytes))
            else:
                rejections.append(
                    Rejection(key, stage, outcome.reason, None, outcome.detail)
                )
    for key in order[position:]:
        rejections.append(
            Rejection(key, stage, "extraction-budget", None, "budget or cap reached before fetch")
        )

    # Decode checks on unique byte content, then the duplicate-bytes rule.
    decoded: dict[str, materialize.DecodedImage] = {}
    decode_reject: dict[str, materialize.ScreenRejection] = {}
    for _, image_id, image_bytes in admitted:
        if image_id in decoded or image_id in decode_reject:
            continue
        outcome = materialize.screen_decoded(image_bytes, config.screen)
        if isinstance(outcome, materialize.DecodedImage):
            decoded[image_id] = outcome
        else:
            decode_reject[image_id] = outcome

    passing: list[tuple[str, str]] = []
    for key, image_id, _ in admitted:
        if image_id in decode_reject:
            r = decode_reject[image_id]
            rejections.append(Rejection(key, stage, r.reason, r.measured, r.detail))
        else:
            passing.append((key, image_id))

    resolution = materialize.resolve_duplicate_bytes(passing)
    for rejected_key, kept_key, image_id in resolution.rejected:
        rejections.append(
            Rejection(
                rejected_key, stage, "duplicate-bytes", None,
                f"kept {kept_key} image {image_id}",
            )
        )

    records = []
    for source_key, image_id in resolution.kept:
        candidate = candidates[source_key]
        d = decoded[image_id]
        records.append(
            ImageRecord(
                image_id=image_id,
                source_key=source_key,
                width=d.width,
                height=d.height,
                image_format=d.image_format,
                captions=candidate.captions,
                attribution=candidate.attribution,
            )
        )
    records.sort(key=lambda r: r.image_id)

    transport_bytes = corpus.bytes_retrieved - transport_start
    meta = _meta(
        tree,
        stage,
        "s01-screen",
        input_count=len(candidates),
        survivors=len(records),
        rejections=rejections,
        config_echo={
            "budget_bytes": budget,
            "materialize_cap": cap,
            "fetch_batch_size": batch_size,
        },
        provider_hashes={"corpus": corpus.config_hash},
        counters={
            "fetched": fetched,
            "budget_stopped": budget_stopped,
            "decision_bytes": decision_bytes,
        },
        bytes_retrieved=transport_bytes,
        bytes_cumulative=_cumulative(tree, "s01-screen") + transport_bytes,
        provider_requests=0,
        code_version=code_version,
    )
    directory = mf.stage_dir(tree, stage)
    directory.mkdir(parents=True, exist_ok=True)
    mf.write_jsonl(
        directory / "records.jsonl", (mf.image_record_to_row(r) for r in records)
    )
    _write_stage(
        tree,
        stage,
        meta,
        [mf.manifest_row(r.image_id, r.source_key) for r in records],
        rejections,
    )
    return meta


def _survivor_ids(tree: ArtifactTree, parent: str) -> list[str]:
    rows = _read_parent_manifest(tree, parent)
    ids = [str(row["image_id"]) for row in rows]
    return sorted(ids)


def _id_to_source(tree: ArtifactTree, parent: str) -> dict[str, str]:
    rows = _read_parent_manifest(tree, parent)
    return {str(row["image_id"]): str(row["source_key"]) for row in rows}


def _model_stage(
    tree: ArtifactTree,
    stage: str,
    parent: str,
    config_echo: Mapping[str, JsonValue],
    provider_name: str,
    provider: object,
    decide: Callable[[list[str], np.ndarray], object],
    estimate: Callable[[Sequence[bytes]], np.ndarray],
    code_version: str,
) -> StageMeta:
    """Shared shell for s03, s04, and s05: load bytes, estimate, judge."""
    ids = _survivor_ids(tree, parent)
    id_to_source = _id_to_source(tree, parent)
    values: list[np.ndarray] = []
    posts_before = getattr(provider, "post_count", 0)
    for start in range(0, len(ids), _BYTE_SLICE):
        chunk = ids[start : start + _BYTE_SLICE]
        values.append(np.asarray(estimate(_load_bytes(tree.data_root, chunk))))
    stacked = (
        np.concatenate(values, axis=0) if values else np.zeros((0,), dtype=np.float32)
    )
    result = decide(ids, stacked)
    provider_requests = int(getattr(provider, "post_count", 0)) - int(posts_before)
    meta = _meta(
        tree,
        stage,
        parent,
        input_count=len(ids),
        survivors=len(result.survivors),
        rejections=result.rejections,
        config_echo=config_echo,
        provider_hashes={provider_name: getattr(provider, "config_hash")},
        counters={},
        bytes_retrieved=0,
        bytes_cumulative=_cumulative(tree, parent),
        provider_requests=provider_requests,
        code_version=code_version,
    )
    _write_stage(
        tree,
        stage,
        meta,
        [mf.manifest_row(i, id_to_source[i]) for i in result.survivors],
        result.rejections,
    )
    return meta


def run_s03_text(
    provider: TextCoverageEstimator, config: CurationConfig, tree: ArtifactTree, code_version: str
) -> StageMeta:
    return _model_stage(
        tree,
        "s03-text",
        "s02-materialize",
        {"max_text_coverage": config.text.max_text_coverage},
        "text_coverage",
        provider,
        lambda ids, values: text.text_decisions(ids, values, config.text.max_text_coverage),
        provider.estimate_text_coverage,
        code_version,
    )


def run_s04_class(
    provider: ZeroShotImageClassifier, config: CurationConfig, tree: ArtifactTree,
    code_version: str,
) -> StageMeta:
    labels = config.classify.labels
    return _model_stage(
        tree,
        "s04-class",
        "s03-text",
        {
            "labels": list(labels),
            "keep_label": config.classify.keep_label,
            "label_template": config.classify.label_template,
        },
        "classifier",
        provider,
        lambda ids, values: classify.class_decisions(
            ids, values, labels, config.classify.keep_label
        ),
        lambda images: provider.classify(images, labels),
        code_version,
    )


def run_s05_object(
    provider: SalientObjectEstimator, config: CurationConfig, tree: ArtifactTree,
    code_version: str,
) -> StageMeta:
    return _model_stage(
        tree,
        "s05-object",
        "s04-class",
        {"min_object_fraction": config.objectsize.min_object_fraction},
        "object_size",
        provider,
        lambda ids, values: objectsize.object_decisions(
            ids, values, config.objectsize.min_object_fraction
        ),
        provider.estimate_salient_object_fraction,
        code_version,
    )


def _vectors_for(
    tree: ArtifactTree, encoder: ImageEncoder, image_ids: Sequence[str]
) -> np.ndarray:
    """Encoder vectors for the given ids, through the .npy cache."""
    encoder_hash = encoder.config_hash
    vectors: dict[str, np.ndarray] = {}
    missing: list[str] = []
    for image_id in image_ids:
        path = mf.vector_path(tree.data_root, encoder_hash, image_id)
        if path.exists():
            vectors[image_id] = np.load(path)
        else:
            missing.append(image_id)
    for start in range(0, len(missing), _BYTE_SLICE):
        chunk = missing[start : start + _BYTE_SLICE]
        encoded = encoder.encode_images(_load_bytes(tree.data_root, chunk))
        for image_id, vector in zip(chunk, encoded):
            path = mf.vector_path(tree.data_root, encoder_hash, image_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp.npy")
            np.save(tmp, vector.astype(np.float32))
            os.replace(tmp, path)
            vectors[image_id] = vector.astype(np.float32)
    return np.stack([vectors[i] for i in image_ids]).astype(np.float32)


def run_s06_neardup(
    encoder: ImageEncoder, config: CurationConfig, tree: ArtifactTree, code_version: str
) -> StageMeta:
    stage = "s06-neardup"
    ids = _survivor_ids(tree, "s05-object")
    id_to_source = _id_to_source(tree, "s05-object")
    records = _read_records(tree)
    areas = [records[i].width * records[i].height for i in ids]
    vectors = (
        _vectors_for(tree, encoder, ids)
        if ids
        else np.zeros((0, 1), dtype=np.float32)
    )
    result = neardup.neardup_decisions(
        ids, areas, vectors, config.neardup.similarity_threshold
    )
    meta = _meta(
        tree,
        stage,
        "s05-object",
        input_count=len(ids),
        survivors=len(result.survivors),
        rejections=result.rejections,
        config_echo={"similarity_threshold": config.neardup.similarity_threshold},
        provider_hashes={"encoder": encoder.config_hash},
        counters={},
        bytes_retrieved=0,
        bytes_cumulative=_cumulative(tree, "s05-object"),
        provider_requests=0,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta,
        [mf.manifest_row(i, id_to_source[i]) for i in result.survivors],
        result.rejections,
    )
    return meta


def run_s07_diversity(
    encoder: ImageEncoder, config: CurationConfig, tree: ArtifactTree, code_version: str
) -> StageMeta:
    stage = "s07-diversity"
    ids = _survivor_ids(tree, "s06-neardup")
    id_to_source = _id_to_source(tree, "s06-neardup")
    vectors = (
        _vectors_for(tree, encoder, ids)
        if ids
        else np.zeros((0, 1), dtype=np.float32)
    )
    result = diversity.diversity_decisions(
        ids,
        vectors,
        config.seeds.cluster_seed,
        config.diversity.cluster_size_divisor,
        config.diversity.cluster_cap,
        config.diversity.kmeans_max_iterations,
    )
    meta = _meta(
        tree,
        stage,
        "s06-neardup",
        input_count=len(ids),
        survivors=len(result.survivors),
        rejections=result.rejections,
        config_echo={
            "cluster_size_divisor": config.diversity.cluster_size_divisor,
            "cluster_cap": config.diversity.cluster_cap,
            "kmeans_max_iterations": config.diversity.kmeans_max_iterations,
            "cluster_seed": config.seeds.cluster_seed,
        },
        provider_hashes={"encoder": encoder.config_hash},
        counters={},
        bytes_retrieved=0,
        bytes_cumulative=_cumulative(tree, "s06-neardup"),
        provider_requests=0,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta,
        [mf.manifest_row(i, id_to_source[i]) for i in result.survivors],
        result.rejections,
    )
    return meta


def run_s08_review(config: CurationConfig, tree: ArtifactTree, code_version: str) -> StageMeta:
    stage = "s08-review"
    ids = _survivor_ids(tree, "s07-diversity")
    id_to_source = _id_to_source(tree, "s07-diversity")
    records = _read_records(tree)
    sample = review.select_review_sample(ids, config.review.sample_size, config.seeds.review_seed)
    entries = []
    import base64

    for image_id in sample:
        caption = records[image_id].captions[0] if records[image_id].captions else ""
        png = review.thumbnail_png(
            mf.load_image_bytes(tree.data_root, image_id), config.review.thumbnail_max_side
        )
        entries.append(
            review.ReviewEntry(
                image_id=image_id,
                caption=caption,
                thumbnail_png_base64=base64.b64encode(png).decode("ascii"),
            )
        )
    directory = mf.stage_dir(tree, stage)
    directory.mkdir(parents=True, exist_ok=True)
    mf.write_jsonl(
        directory / "sample.jsonl",
        ({"image_id": e.image_id, "caption": e.caption} for e in entries),
    )
    html = review.contact_sheet_html(entries, mf.stage_label(tree, stage))
    mf.write_bytes_atomic(directory / "contact_sheet.html", html.encode("utf-8"))
    meta = _meta(
        tree,
        stage,
        "s07-diversity",
        input_count=len(ids),
        survivors=len(ids),
        rejections=(),
        config_echo={
            "sample_size": config.review.sample_size,
            "review_seed": config.seeds.review_seed,
        },
        provider_hashes={},
        counters={"sampled_for_review": len(sample)},
        bytes_retrieved=0,
        bytes_cumulative=_cumulative(tree, "s07-diversity"),
        provider_requests=0,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta, [mf.manifest_row(i, id_to_source[i]) for i in ids], ()
    )
    return meta


def _read_review(tree: ArtifactTree):
    path = mf.stage_dir(tree, "s08-review") / "review.json"
    if not path.exists():
        raise GateHalt("awaiting-review")
    import json

    record = mf.parse_review(json.loads(path.read_text(encoding="utf-8")), str(path))
    if record.verdict != "pass":
        raise GateHalt("review-rejected")
    return record


def run_s09_release(
    corpus: SourceCorpus,
    config: CurationConfig,
    tree: ArtifactTree,
    config_path: Path,
    releases_root: Path,
    code_version: str,
    clock: Callable[[], str],
) -> tuple[StageMeta, str, str, Path]:
    stage = "s09-release"
    record = _read_review(tree)
    rows = _read_parent_manifest(tree, "s08-review")
    ids = sorted(str(row["image_id"]) for row in rows)
    id_to_source = {str(r["image_id"]): str(r["source_key"]) for r in rows}
    pool_version = release.pool_version_id(tree.corpus_id, tree.curation_config_hash, ids)
    label = release.release_label(config.release.tag, pool_version)

    funnel: dict[str, JsonValue] = {}
    for prior in STAGE_NAMES[: STAGE_NAMES.index(stage)]:
        prior_meta = mf.read_meta(tree, prior)
        funnel[prior] = {
            "input": prior_meta.input_count,
            "survivors": prior_meta.survivor_count,
            "rejections": {k: v for k, v in prior_meta.rejections_by_reason},
        }
    identity = corpus.identity
    content: dict[str, JsonValue] = {
        "label": label,
        "pool_version_id": pool_version,
        "corpus_identity": {
            "provider": identity.provider,
            "repo_id": identity.repo_id,
            "revision": identity.revision,
            "config_name": identity.config_name,
            "split": identity.split,
        },
        "corpus_id": tree.corpus_id,
        "curation_config_hash": tree.curation_config_hash,
        "config_path": str(config_path),
        "image_count": len(ids),
        "funnel": funnel,
        "review": {
            "verdict": record.verdict,
            "reviewer": record.reviewer,
            "date": record.date,
            "notes": record.notes,
        },
        "dev_only": config.release.dev_only,
        "code_version": code_version,
        "created_at": clock(),
    }
    releases_root.mkdir(parents=True, exist_ok=True)
    record_path = mf.write_release_record(releases_root, label, content)
    meta = _meta(
        tree,
        stage,
        "s08-review",
        input_count=len(ids),
        survivors=len(ids),
        rejections=(),
        config_echo={"tag": config.release.tag, "dev_only": config.release.dev_only},
        provider_hashes={},
        counters={"image_count": len(ids)},
        bytes_retrieved=0,
        bytes_cumulative=_cumulative(tree, "s08-review"),
        provider_requests=0,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta, [mf.manifest_row(i, id_to_source[i]) for i in ids], ()
    )
    return meta, pool_version, label, record_path


# --- orchestration ---------------------------------------------------------


def _normalize_stage(value: str) -> str:
    for name in STAGE_NAMES:
        if value == name or value == name.split("-", 1)[0]:
            return name
    raise ValueError(f"unknown stage: {value!r} (expected one of {list(STAGE_NAMES)})")


def _utc_now_iso() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _report_from_meta(meta: StageMeta, skipped: bool) -> StageReport:
    return StageReport(
        stage=meta.stage,
        label=meta.label,
        input_count=meta.input_count,
        survivor_count=meta.survivor_count,
        rejections_by_reason=meta.rejections_by_reason,
        bytes_retrieved=meta.bytes_retrieved,
        bytes_cumulative=meta.bytes_cumulative,
        provider_requests=meta.provider_requests,
        skipped=skipped,
    )


def run_curation(
    config: CurationConfig,
    *,
    config_path: Path,
    data_root: Path,
    releases_root: Path,
    code_version: str,
    through: str | None = None,
    force_from: str | None = None,
    corpus: SourceCorpus | None = None,
    clock: Callable[[], str] | None = None,
    report_only: bool = False,
) -> RunReport:
    """Run the pipeline through the requested stage. The library API.

    The s08 gate: when the run gets to s09 and review.json is missing
    or carries a negative verdict, the run stops with a status in the
    report - nothing raises. With report_only the runner executes
    nothing: it reads the complete stages and stops at the first stage
    that is not complete.
    """
    corpus = corpus if corpus is not None else wire_corpus(config)
    clock = clock if clock is not None else _utc_now_iso
    through_stage = _normalize_stage(through) if through else STAGE_NAMES[-1]

    hashes = provider_config_hashes(config, corpus)
    tree = ArtifactTree(
        data_root=data_root,
        corpus_id=_corpus_id(corpus),
        corpus_slug=mf.corpus_slug(corpus.identity.repo_id),
        curation_config_hash=curation_config_hash(config, hashes),
    )

    if force_from is not None:
        start = STAGE_NAMES.index(_normalize_stage(force_from))
        for stage in STAGE_NAMES[start:]:
            directory = mf.stage_dir(tree, stage)
            if directory.exists():
                shutil.rmtree(directory)

    reports: list[StageReport] = []
    halted_at: str | None = None
    halt_reason: str | None = None
    pool_version: str | None = None
    label: str | None = None
    record_path: Path | None = None

    for stage in STAGE_NAMES[: STAGE_NAMES.index(through_stage) + 1]:
        if mf.stage_is_complete(tree, stage):
            reports.append(_report_from_meta(mf.read_meta(tree, stage), skipped=True))
            if stage == "s09-release":
                pool_version, label, record_path = _release_facts(tree, config)
            continue
        if report_only:
            break
        started = clock()
        wall_start = time.monotonic()
        try:
            meta = _execute_stage(
                stage, corpus, config, tree, config_path, releases_root, code_version, clock
            )
        except GateHalt as halt:
            halted_at = "s08-review"
            halt_reason = halt.reason
            break
        if stage == "s09-release":
            meta, pool_version, label, record_path = meta
        _write_timings(tree, stage, started, clock(), time.monotonic() - wall_start)
        reports.append(_report_from_meta(meta, skipped=False))

    return RunReport(
        corpus_id=tree.corpus_id,
        corpus_slug=tree.corpus_slug,
        curation_config_hash=tree.curation_config_hash,
        stages=tuple(reports),
        halted_at=halted_at,
        halt_reason=halt_reason,
        pool_version_id=pool_version,
        release_label=label,
        release_record_path=None if record_path is None else str(record_path),
    )


def _corpus_id(corpus: SourceCorpus) -> str:
    identity = corpus.identity
    return sha256_hex(
        canonical_json(
            {
                "provider": identity.provider,
                "repo_id": identity.repo_id,
                "revision": identity.revision,
                "config_name": identity.config_name,
                "split": identity.split,
            }
        )
    )


def _release_facts(
    tree: ArtifactTree, config: CurationConfig
) -> tuple[str, str, Path | None]:
    rows = _read_parent_manifest(tree, "s09-release")
    ids = sorted(str(row["image_id"]) for row in rows)
    pool_version = release.pool_version_id(tree.corpus_id, tree.curation_config_hash, ids)
    label = release.release_label(config.release.tag, pool_version)
    return pool_version, label, None


def _execute_stage(
    stage: str,
    corpus: SourceCorpus,
    config: CurationConfig,
    tree: ArtifactTree,
    config_path: Path,
    releases_root: Path,
    code_version: str,
    clock: Callable[[], str],
):
    if stage == "s00-snapshot":
        return run_s00_snapshot(corpus, config, tree, code_version)
    if stage == "s01-screen":
        return run_s01_screen(config, tree, code_version)
    if stage == "s02-materialize":
        return run_s02_materialize(corpus, config, tree, code_version)
    if stage == "s03-text":
        provider = _wire_slot("text_coverage", config, tree.data_root)
        return run_s03_text(provider, config, tree, code_version)
    if stage == "s04-class":
        provider = _wire_slot("classifier", config, tree.data_root)
        return run_s04_class(provider, config, tree, code_version)
    if stage == "s05-object":
        provider = _wire_slot("object_size", config, tree.data_root)
        return run_s05_object(provider, config, tree, code_version)
    if stage == "s06-neardup":
        encoder = _wire_slot("encoder", config, tree.data_root)
        return run_s06_neardup(encoder, config, tree, code_version)
    if stage == "s07-diversity":
        encoder = _wire_slot("encoder", config, tree.data_root)
        return run_s07_diversity(encoder, config, tree, code_version)
    if stage == "s08-review":
        return run_s08_review(config, tree, code_version)
    if stage == "s09-release":
        return run_s09_release(
            corpus, config, tree, config_path, releases_root, code_version, clock
        )
    raise ValueError(f"unknown stage: {stage}")


def _write_timings(
    tree: ArtifactTree, stage: str, started: str, finished: str, seconds: float
) -> None:
    mf.write_json_pretty(
        mf.stage_dir(tree, stage) / "timings.json",
        {"started": started, "finished": finished, "seconds": quantize_measured(seconds)},
    )


def format_funnel(report: RunReport) -> str:
    """Text funnel for the command line: numbers, not adjectives."""
    lines = [
        f"corpus {report.corpus_slug} ({report.corpus_id[:8]})  "
        f"config c{report.curation_config_hash[:8]}",
    ]
    for entry in report.stages:
        flag = " (reused)" if entry.skipped else ""
        rejects = ", ".join(f"{k}={v}" for k, v in entry.rejections_by_reason) or "-"
        lines.append(
            f"{entry.stage}: in={entry.input_count} out={entry.survivor_count} "
            f"bytes={entry.bytes_retrieved} cum={entry.bytes_cumulative} "
            f"posts={entry.provider_requests} rejected[{rejects}]{flag}"
        )
    if report.halted_at is not None:
        lines.append(f"halted at {report.halted_at}: {report.halt_reason}")
    if report.pool_version_id is not None:
        lines.append(
            f"released {report.release_label} pool_version={report.pool_version_id[:16]}"
        )
    return "\n".join(lines)
