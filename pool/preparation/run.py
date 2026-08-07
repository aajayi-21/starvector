"""The imperative shell of the preparation pipeline.

Spec: docs/specs/pool-preparation.md sections 10 and 12. This module
wires providers from configuration, sequences stages p00 through p09,
resumes from complete stage directories, and reports the U1 POST and
cache-hit counts. Stage logic itself is pure and lives in
pool/preparation/stages/.
"""

import datetime as _datetime
import os
import shutil
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np

from core.canonical import JsonValue, quantize_measured, sha256_hex
from pool.preparation import manifest as mf
from pool.preparation.config import (
    SLOT_NAMES,
    PreparationConfig,
    SlotSection,
    preparation_config_hash,
)
from pool.preparation.stages import (
    boxes,
    cap,
    elements,
    intake,
    linedraw,
    neardup,
    normalize,
    outline,
    release,
    vocabulary,
)
from pool.preparation.types import (
    ELEMENT_FIELDS,
    STAGE_NAMES,
    IntakeIssue,
    IntakeRecord,
    PoolReleaseRecord,
    PreparationReport,
    PreparationTree,
    ReleaseFacts,
    StageMeta,
    StageReport,
)

# Shell-only constant: how many images are decoded into memory at one
# time. This limits memory use and cannot change results.
_BYTE_SLICE = 256

# Which slot each provider-backed stage uses. p09 aggregates the U1
# counts from these stages' metas into the preparation record.
_USAGE_STAGES: tuple[tuple[str, str], ...] = (
    ("p01-elements", "describer"),
    ("p04-vocabulary", "text_encoder"),
    ("p05-linedraw", "line_drawer"),
    ("p06-outline", "image_encoder"),
    ("p07-boxes", "element_boxes"),
)


def _slot_hash(slot_name: str, slot: SlotSection, config: PreparationConfig) -> str:
    """The config hash of one slot, computable with no client and no GPU.

    The local modules import without torch at their top level, and thus
    hashing a local slot stays cheap.
    """
    if slot.provider == "fake":
        return getattr(_wire_fake(slot_name, slot), "config_hash")
    if slot.provider == "openrouter":
        if slot_name == "describer":
            from providers.openrouter.describer import describer_config_hash

            return describer_config_hash(_describer_slot_config(slot, config))
        if slot_name in ("text_encoder", "image_encoder"):
            from providers.openrouter.embeddings import embedding_config_hash

            return embedding_config_hash(_embedding_slot_config(slot_name, slot, config))
        if slot_name == "element_boxes":
            from providers.openrouter.boxes import box_config_hash

            return box_config_hash(_box_slot_config(slot, config))
    if slot.provider == "local":
        if slot_name == "line_drawer":
            from providers.local.lineart import lineart_config_hash

            return lineart_config_hash(_lineart_config(config))
        if slot_name == "text_encoder":
            from providers.local.siglip import siglip_text_config_hash

            return siglip_text_config_hash(_siglip_config(slot_name, slot))
        if slot_name == "image_encoder":
            from providers.local.siglip import siglip_image_config_hash

            return siglip_image_config_hash(_siglip_config(slot_name, slot))
    raise ValueError(f"unknown provider for slot {slot_name}: {slot.provider}")


def provider_config_hashes(
    config: PreparationConfig, providers: Mapping[str, object] | None = None
) -> dict[str, str]:
    """The five hashes that enter preparation_config_hash.

    An injected provider instance (tests) supplies its own hash. The
    other slots hash from configuration without wiring.
    """
    hashes: dict[str, str] = {}
    for slot_name in SLOT_NAMES:
        if providers is not None and slot_name in providers:
            hashes[slot_name] = getattr(providers[slot_name], "config_hash")
        else:
            hashes[slot_name] = _slot_hash(
                slot_name, getattr(config.providers, slot_name), config
            )
    return hashes


def _wire_fake(slot_name: str, slot: SlotSection):
    if slot_name == "describer":
        from providers.fake.describer import FakeVlmDescriber

        return FakeVlmDescriber()
    if slot_name == "text_encoder":
        from providers.fake.text_encoder import FakeTextEncoder

        return FakeTextEncoder(dimension=slot.dimension or 64)
    if slot_name == "image_encoder":
        from providers.fake.encoder import FakeImageEncoder

        return FakeImageEncoder(dimension=slot.dimension or 64)
    if slot_name == "line_drawer":
        from providers.fake.linedrawer import FakeLineDrawer

        return FakeLineDrawer()
    if slot_name == "element_boxes":
        from providers.fake.boxes import FakeElementBoxDetector

        return FakeElementBoxDetector()
    raise ValueError(f"unknown fake slot: {slot_name}")


def _describer_slot_config(slot: SlotSection, config: PreparationConfig):
    from providers.openrouter.describer import DESCRIBER_MAX_TOKENS, DescriberSlotConfig

    counts = config.elements.counts
    return DescriberSlotConfig(
        slot="describer",
        model=slot.model or config.providers.openrouter.default_model,
        template=slot.instruction_template or "",
        temperature=0.0,
        seed=0,
        max_tokens=DESCRIBER_MAX_TOKENS,
        reasoning_enabled=False,
        response_format_mode=config.providers.openrouter.response_format_mode,
        objects_count=counts.objects,
        materials_count=counts.materials,
        colors_count=counts.colors,
        shapes_count=counts.shapes,
        ambience_count=counts.ambience,
    )


def _embedding_slot_config(slot_name: str, slot: SlotSection, config: PreparationConfig):
    from providers.openrouter.embeddings import EmbeddingSlotConfig

    if slot.dimension is None:
        raise ValueError(f"providers.{slot_name}.dimension: required for the openrouter provider")
    return EmbeddingSlotConfig(
        slot=slot_name,
        model=slot.model or config.providers.openrouter.default_model,
        dimension=slot.dimension,
        encoding_format="float",
    )


def _box_slot_config(slot: SlotSection, config: PreparationConfig):
    from providers.openrouter.boxes import BOXES_MAX_TOKENS, BoxSlotConfig

    return BoxSlotConfig(
        slot="element_boxes",
        model=slot.model or config.providers.openrouter.default_model,
        template=slot.instruction_template or "",
        temperature=0.0,
        seed=0,
        max_tokens=BOXES_MAX_TOKENS,
        reasoning_enabled=False,
        response_format_mode=config.providers.openrouter.response_format_mode,
    )


def _lineart_config(config: PreparationConfig):
    from providers.local.lineart import LineartConfig

    section = config.linedraw
    return LineartConfig(
        weights_id="lllyasviel/Annotators",
        coarse=False,
        detect_resolution=section.canvas_px,
        binarize_threshold=section.binarize_threshold,
        min_segment_px=section.min_segment_px,
        canvas_size=section.canvas_px,
        line_width=section.line_width_px,
        anti_alias=section.antialias,
    )


def _siglip_config(slot_name: str, slot: SlotSection):
    from providers.local.siglip import SiglipConfig

    if slot.model is None:
        raise ValueError(f"providers.{slot_name}.model: required for the local provider")
    if slot.dimension is None:
        raise ValueError(f"providers.{slot_name}.dimension: required for the local provider")
    # The revision is a placeholder that the first full-scale run pins.
    # The fake and development paths do not build this config.
    return SiglipConfig(
        checkpoint=slot.model,
        revision="main-pinned-at-first-use",
        dimension=slot.dimension,
        dtype="float32",
    )


def _wire_slot(slot_name: str, config: PreparationConfig, data_root: Path):
    """Build one model provider instance right before its stage runs."""
    slot = getattr(config.providers, slot_name)
    if slot.provider == "fake":
        return _wire_fake(slot_name, slot)
    if slot.provider == "openrouter":
        from providers.openrouter.client import OpenRouterClient, OpenRouterClientConfig

        section = config.providers.openrouter
        client = OpenRouterClient(
            OpenRouterClientConfig(
                base_url="https://openrouter.ai/api/v1",
                max_concurrency=section.max_concurrency,
                requests_per_second=section.requests_per_second,
                timeout_seconds=section.timeout_seconds,
                retry_limit=section.retry_limit,
            ),
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        )
        cache_root = data_root / "cache" / "openrouter"
        if slot_name == "describer":
            from providers.openrouter.describer import OpenRouterVlmDescriber

            return OpenRouterVlmDescriber(_describer_slot_config(slot, config), client, cache_root)
        if slot_name == "text_encoder":
            from providers.openrouter.embeddings import OpenRouterTextEncoder

            return OpenRouterTextEncoder(
                _embedding_slot_config(slot_name, slot, config), client, cache_root
            )
        if slot_name == "image_encoder":
            from providers.openrouter.embeddings import OpenRouterImageEncoder

            return OpenRouterImageEncoder(
                _embedding_slot_config(slot_name, slot, config), client, cache_root
            )
        if slot_name == "element_boxes":
            from providers.openrouter.boxes import OpenRouterElementBoxDetector

            return OpenRouterElementBoxDetector(_box_slot_config(slot, config), client, cache_root)
    if slot.provider == "local":
        if slot_name == "line_drawer":
            from providers.local.lineart import LocalLineDrawer

            return LocalLineDrawer(_lineart_config(config))
        if slot_name == "text_encoder":
            from providers.local.siglip import SiglipTextEncoder

            return SiglipTextEncoder(_siglip_config(slot_name, slot))
        if slot_name == "image_encoder":
            from providers.local.siglip import SiglipImageEncoder

            return SiglipImageEncoder(_siglip_config(slot_name, slot))
    raise ValueError(f"unknown provider for slot {slot_name}: {slot.provider}")


def _meta(
    tree: PreparationTree,
    stage: str,
    parent: str | None,
    image_count: int,
    config_echo: Mapping[str, JsonValue],
    provider_hashes: Mapping[str, str],
    counters: Mapping[str, int],
    array_shapes: Mapping[str, Sequence[int]],
    provider_posts: int,
    provider_cache_hits: int,
    code_version: str,
) -> StageMeta:
    return StageMeta(
        stage=stage,
        label=mf.stage_label(tree, stage),
        parent_stage=parent,
        image_count=image_count,
        config_echo=tuple(sorted(config_echo.items())),
        provider_config_hashes=tuple(sorted((k, v) for k, v in provider_hashes.items())),
        counters=tuple(sorted(counters.items())),
        array_shapes=tuple(
            sorted((k, tuple(int(d) for d in v)) for k, v in array_shapes.items())
        ),
        provider_posts=provider_posts,
        provider_cache_hits=provider_cache_hits,
        code_version=code_version,
    )


def _write_stage(
    tree: PreparationTree,
    stage: str,
    meta: StageMeta,
    rows_by_file: Mapping[str, Sequence[dict[str, JsonValue]]],
) -> None:
    """Write one stage directory: data rows first, meta last."""
    directory = mf.stage_dir(tree, stage)
    directory.mkdir(parents=True, exist_ok=True)
    for name, rows in rows_by_file.items():
        mf.write_jsonl(directory / name, rows)
    mf.write_meta(tree, stage, meta)


def _load_bytes(data_root: Path, image_ids: Sequence[str]) -> list[bytes]:
    return [mf.load_image_bytes(data_root, image_id) for image_id in image_ids]


def _intake_ids(tree: PreparationTree) -> list[str]:
    rows = mf.read_jsonl(mf.stage_dir(tree, "p00-intake") / "records.jsonl")
    return [str(row["image_id"]) for row in rows]


def _element_lists(
    tree: PreparationTree, stage: str, name: str
) -> tuple[list[str], list[tuple[str, ...]]]:
    rows = mf.read_jsonl(mf.stage_dir(tree, stage) / name)
    ids: list[str] = []
    sequences: list[tuple[str, ...]] = []
    for row in rows:
        image_id, entries = mf.row_to_element_list(row)
        ids.append(image_id)
        sequences.append(entries)
    return ids, sequences


class _UsageDelta:
    """U1 accounting around one provider-backed stage, duck-typed."""

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


# --- stage runners ---------------------------------------------------------


def run_p00_intake(
    record: PoolReleaseRecord, config: PreparationConfig, tree: PreparationTree,
    code_version: str,
) -> StageMeta:
    stage = "p00-intake"
    manifest_path = (
        tree.data_root / "curation" / record.corpus_id[:8]
        / record.curation_config_hash[:8] / "s09-release" / "manifest.jsonl"
    )
    rows = mf.read_jsonl(manifest_path)
    ids = intake.intake_check_membership(record, [str(row["image_id"]) for row in rows])
    records: list[IntakeRecord] = []
    issues: list[IntakeIssue] = []
    for image_id in ids:
        try:
            image_bytes = mf.load_image_bytes(tree.data_root, image_id)
        except mf.ManifestError:
            issues.append(IntakeIssue(image_id=image_id, kind="missing-bytes", detail=""))
            continue
        outcome = intake.intake_examine_image(image_id, image_bytes)
        if isinstance(outcome, IntakeIssue):
            issues.append(outcome)
        else:
            records.append(outcome)
    if issues:
        named = ", ".join(f"{issue.image_id} ({issue.kind})" for issue in issues)
        raise mf.ManifestError(
            f"{stage}: {len(issues)} image(s) did not clear intake: {named}. "
            "R13 permits no skip - fix the image store or cut a new curation release."
        )
    meta = _meta(
        tree,
        stage,
        None,
        image_count=len(records),
        config_echo={
            "release_record": config.input.release_record,
            "pool_version_id": record.pool_version_id,
        },
        provider_hashes={},
        counters={},
        array_shapes={},
        provider_posts=0,
        provider_cache_hits=0,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta,
        {"records.jsonl": [mf.intake_record_to_row(r) for r in records]},
    )
    return meta


def run_p01_elements(
    describer: object, config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p01-elements"
    ids = _intake_ids(tree)
    usage = _UsageDelta(describer)
    rows_out: list[dict[str, JsonValue]] = []
    for start in range(0, len(ids), _BYTE_SLICE):
        chunk = ids[start : start + _BYTE_SLICE]
        responses = describer.describe_images(_load_bytes(tree.data_root, chunk))
        for image_id, response in elements.elements_align(chunk, responses):
            rows_out.append(mf.element_row(image_id, response))
    counts = config.elements.counts
    meta = _meta(
        tree,
        stage,
        "p00-intake",
        image_count=len(ids),
        config_echo={"counts": {field: getattr(counts, field) for field in ELEMENT_FIELDS}},
        provider_hashes={"describer": getattr(describer, "config_hash")},
        counters={},
        array_shapes={},
        provider_posts=usage.posts,
        provider_cache_hits=usage.cache_hits,
        code_version=code_version,
    )
    _write_stage(tree, stage, meta, {"elements.jsonl": rows_out})
    return meta


def run_p02_normalize(
    config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p02-normalize"
    rows = mf.read_jsonl(mf.stage_dir(tree, "p01-elements") / "elements.jsonl")
    rows_out: list[dict[str, JsonValue]] = []
    for row in rows:
        image_id, response = mf.row_to_element_response(row)
        rows_out.append(mf.element_list_row(image_id, normalize.normalize_elements(response)))
    meta = _meta(
        tree,
        stage,
        "p01-elements",
        image_count=len(rows_out),
        config_echo={"normalize_rule": config.elements.normalize_rule},
        provider_hashes={},
        counters={},
        array_shapes={},
        provider_posts=0,
        provider_cache_hits=0,
        code_version=code_version,
    )
    _write_stage(tree, stage, meta, {"normalized.jsonl": rows_out})
    return meta


def run_p03_cap(
    config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p03-cap"
    ids, sequences = _element_lists(tree, "p02-normalize", "normalized.jsonl")
    capped, cuts = cap.cap_decisions(ids, sequences, config.elements.max_elements)
    meta = _meta(
        tree,
        stage,
        "p02-normalize",
        image_count=len(ids),
        config_echo={"max_elements": config.elements.max_elements},
        provider_hashes={},
        counters={"cuts": len(cuts)},
        array_shapes={},
        provider_posts=0,
        provider_cache_hits=0,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta,
        {
            "capped.jsonl": [
                mf.element_list_row(image_id, entries)
                for image_id, entries in zip(ids, capped)
            ],
            "cuts.jsonl": [mf.cut_to_row(cut) for cut in cuts],
        },
    )
    return meta


def run_p04_vocabulary(
    text_encoder: object, config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p04-vocabulary"
    ids, capped = _element_lists(tree, "p03-cap", "capped.jsonl")
    vocab = vocabulary.vocabulary_build(capped)
    if not vocab:
        raise mf.ManifestError(f"{stage}: the vocabulary is empty - no element survived p03")
    frequencies = vocabulary.vocabulary_frequencies(vocab, capped)
    usage = _UsageDelta(text_encoder)
    parts: list[np.ndarray] = []
    for start in range(0, len(vocab), _BYTE_SLICE):
        chunk = list(vocab[start : start + _BYTE_SLICE])
        parts.append(np.asarray(text_encoder.encode_texts(chunk)))
    vectors = np.concatenate(parts, axis=0).astype(np.float32)  # (V, d)
    if vectors.ndim != 2 or vectors.shape[0] != len(vocab):
        raise mf.ManifestError(
            f"{stage}: encoder output shape {vectors.shape} does not agree with "
            f"{len(vocab)} vocabulary entries"
        )
    norms = np.linalg.norm(vectors, axis=1)  # (V,)
    if np.any(np.abs(norms - 1.0) > 1e-3):
        raise mf.ManifestError(f"{stage}: encoder output rows are not unit-norm (R9)")
    incidence = vocabulary.vocabulary_incidence(ids, capped, vocab, config.elements.max_elements)
    mean = vocabulary.vector_mean(vectors)  # (d,)
    directory = mf.stage_dir(tree, stage)
    directory.mkdir(parents=True, exist_ok=True)
    mf.save_npy_atomic(directory / "vocabulary_vectors.npy", vectors)
    mf.save_npy_atomic(directory / "incidence.npy", incidence)
    mf.save_npy_atomic(directory / "element_space_mean.npy", mean)
    meta = _meta(
        tree,
        stage,
        "p03-cap",
        image_count=len(ids),
        config_echo={"max_elements": config.elements.max_elements},
        provider_hashes={"text_encoder": getattr(text_encoder, "config_hash")},
        counters={"vocabulary_entries": len(vocab)},
        array_shapes={
            "vocabulary_vectors": vectors.shape,
            "incidence": incidence.shape,
            "element_space_mean": mean.shape,
        },
        provider_posts=usage.posts,
        provider_cache_hits=usage.cache_hits,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta,
        {
            "vocabulary.jsonl": [
                mf.vocabulary_row(index, element, frequency)
                for index, (element, frequency) in enumerate(zip(vocab, frequencies))
            ]
        },
    )
    return meta


def run_p05_linedraw(
    line_drawer: object, config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p05-linedraw"
    ids = _intake_ids(tree)
    drawer_hash = getattr(line_drawer, "config_hash")
    missing = [
        image_id for image_id in ids
        if not mf.linedraw_path(tree.data_root, drawer_hash, image_id).exists()
    ]
    usage = _UsageDelta(line_drawer)
    for start in range(0, len(missing), _BYTE_SLICE):
        chunk = missing[start : start + _BYTE_SLICE]
        drawings = line_drawer.draw_lines(_load_bytes(tree.data_root, chunk))
        if len(drawings) != len(chunk):
            raise mf.ManifestError(
                f"{stage}: draw_lines gave {len(drawings)} drawing(s) for "
                f"{len(chunk)} image(s)"
            )
        for image_id, drawing in zip(chunk, drawings):
            linedraw.linedraw_check_png(image_id, drawing)
            mf.write_bytes_atomic(
                mf.linedraw_path(tree.data_root, drawer_hash, image_id), drawing
            )
    rows_out: list[dict[str, JsonValue]] = []
    for image_id in ids:
        path = mf.linedraw_path(tree.data_root, drawer_hash, image_id)
        rows_out.append(
            mf.drawing_row(
                image_id, linedraw.linedraw_key(drawer_hash, image_id), path.stat().st_size
            )
        )
    meta = _meta(
        tree,
        stage,
        "p04-vocabulary",
        image_count=len(ids),
        config_echo={
            "binarize_threshold": config.linedraw.binarize_threshold,
            "min_segment_px": config.linedraw.min_segment_px,
            "canvas_px": config.linedraw.canvas_px,
            "line_width_px": config.linedraw.line_width_px,
            "background": config.linedraw.background,
            "antialias": config.linedraw.antialias,
        },
        provider_hashes={"line_drawer": drawer_hash},
        # No drawn-against-cached split here: those counts change with
        # local cache warmth, and meta.json must stay deterministic
        # across a cold run and a resume (spec section 15, invariant 9).
        counters={},
        array_shapes={},
        provider_posts=usage.posts,
        provider_cache_hits=usage.cache_hits,
        code_version=code_version,
    )
    _write_stage(tree, stage, meta, {"drawings.jsonl": rows_out})
    return meta


def run_p06_outline(
    image_encoder: object, config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p06-outline"
    ids = _intake_ids(tree)
    drawer_hash = dict(mf.read_meta(tree, "p05-linedraw").provider_config_hashes)["line_drawer"]
    encoder_hash = getattr(image_encoder, "config_hash")
    # The image-level cache key covers the two hashes: a change to the
    # drawings or the encoder moves the cached vectors (spec section 6).
    combined_hash = sha256_hex(encoder_hash + drawer_hash)
    rows_for_image = len(outline.ROW_LAYOUT)
    per_image: dict[str, np.ndarray] = {}
    missing: list[str] = []
    for image_id in ids:
        path = mf.vector_path(tree.data_root, combined_hash, image_id)
        if path.exists():
            array = np.load(path)
            if array.ndim != 2 or array.shape[0] != rows_for_image:
                raise mf.ManifestError(
                    f"{path}: cached outline vectors have shape {array.shape}, "
                    f"not ({rows_for_image}, d)"
                )
            per_image[image_id] = array.astype(np.float32)
        else:
            missing.append(image_id)
    usage = _UsageDelta(image_encoder)
    for start in range(0, len(missing), _BYTE_SLICE):
        chunk = missing[start : start + _BYTE_SLICE]
        batch: list[bytes] = []
        for image_id in chunk:
            drawing_path = mf.linedraw_path(tree.data_root, drawer_hash, image_id)
            try:
                drawing = drawing_path.read_bytes()
            except OSError as error:
                raise mf.ManifestError(
                    f"{drawing_path}: line drawing missing from the cache: {error}"
                ) from error
            batch.extend(outline.outline_crop_images(drawing, config.outline.crop_fraction))
        encoded = np.asarray(image_encoder.encode_images(batch))  # (6 * B, d)
        if encoded.ndim != 2 or encoded.shape[0] != len(batch):
            raise mf.ManifestError(
                f"{stage}: encoder output shape {encoded.shape} does not agree with "
                f"{len(batch)} crop images"
            )
        for position, image_id in enumerate(chunk):
            array = encoded[
                position * rows_for_image : (position + 1) * rows_for_image
            ].astype(np.float32)  # (6, d)
            mf.save_npy_atomic(mf.vector_path(tree.data_root, combined_hash, image_id), array)
            per_image[image_id] = array
    stacked = np.stack([per_image[image_id] for image_id in ids]).astype(np.float32)
    # (N, 6, d). The D11 mean runs across all stored rows.
    mean = vocabulary.vector_mean(stacked.reshape(-1, stacked.shape[2]))  # (d,)
    directory = mf.stage_dir(tree, stage)
    directory.mkdir(parents=True, exist_ok=True)
    mf.save_npy_atomic(directory / "outline_vectors.npy", stacked)
    mf.save_npy_atomic(directory / "outline_space_mean.npy", mean)
    meta = _meta(
        tree,
        stage,
        "p05-linedraw",
        image_count=len(ids),
        config_echo={
            "crop_fraction": config.outline.crop_fraction,
            "crop_grid": config.outline.crop_grid,
        },
        provider_hashes={"image_encoder": encoder_hash, "line_drawer": drawer_hash},
        # No encoded-against-cached split - see the p05 counter note.
        counters={},
        array_shapes={"outline_vectors": stacked.shape, "outline_space_mean": mean.shape},
        provider_posts=usage.posts,
        provider_cache_hits=usage.cache_hits,
        code_version=code_version,
    )
    _write_stage(tree, stage, meta, {})
    return meta


def run_p07_boxes(
    detector: object, config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p07-boxes"
    ids, capped = _element_lists(tree, "p03-cap", "capped.jsonl")
    usage = _UsageDelta(detector)
    rows_out: list[dict[str, JsonValue]] = []
    for start in range(0, len(ids), _BYTE_SLICE):
        chunk_ids = ids[start : start + _BYTE_SLICE]
        chunk_lists = capped[start : start + _BYTE_SLICE]
        responses = detector.detect_boxes(
            _load_bytes(tree.data_root, chunk_ids),
            [list(entries) for entries in chunk_lists],
        )
        if len(responses) != len(chunk_ids):
            raise mf.ManifestError(
                f"{stage}: detect_boxes gave {len(responses)} response(s) for "
                f"{len(chunk_ids)} image(s)"
            )
        for image_id, entries, response in zip(chunk_ids, chunk_lists, responses):
            boxes.boxes_validate(image_id, entries, response)
            rows_out.append(mf.box_row(image_id, response))
    meta = _meta(
        tree,
        stage,
        "p06-outline",
        image_count=len(ids),
        config_echo={},
        provider_hashes={"element_boxes": getattr(detector, "config_hash")},
        counters={},
        array_shapes={},
        provider_posts=usage.posts,
        provider_cache_hits=usage.cache_hits,
        code_version=code_version,
    )
    _write_stage(tree, stage, meta, {"boxes.jsonl": rows_out})
    return meta


def run_p08_neardup(
    config: PreparationConfig, tree: PreparationTree, code_version: str
) -> StageMeta:
    stage = "p08-neardup"
    ids = _intake_ids(tree)
    stacked = np.load(mf.stage_dir(tree, "p06-outline") / "outline_vectors.npy")  # (N, 6, d)
    full_rows = np.ascontiguousarray(stacked[:, 0, :])  # (N, d) full-image rows only (D9)
    rows, histogram = neardup.neardup_groups(
        ids, full_rows, config.neardup.similarity_threshold
    )
    meta = _meta(
        tree,
        stage,
        "p07-boxes",
        image_count=len(ids),
        config_echo={"similarity_threshold": config.neardup.similarity_threshold},
        provider_hashes={},
        counters={f"members-{member_count}": group_count
                  for member_count, group_count in histogram},
        array_shapes={},
        provider_posts=0,
        provider_cache_hits=0,
        code_version=code_version,
    )
    _write_stage(
        tree, stage, meta, {"groups.jsonl": [mf.group_to_row(row) for row in rows]}
    )
    return meta


def run_p09_release(
    config: PreparationConfig,
    tree: PreparationTree,
    config_path: Path,
    releases_root: Path,
    provider_hashes: Mapping[str, str],
    code_version: str,
    clock: Callable[[], str],
) -> tuple[StageMeta, ReleaseFacts]:
    stage = "p09-release"
    ids = _intake_ids(tree)
    preparation_version = release.release_preparation_version_id(
        tree.pool_version_id, tree.preparation_config_hash
    )
    label = release.release_label(config.release.tag, preparation_version)

    artifacts: dict[str, str] = {}
    for prior in STAGE_NAMES[: STAGE_NAMES.index(stage)]:
        directory = mf.stage_dir(tree, prior)
        data_files = list(directory.glob("*.jsonl")) + list(directory.glob("*.npy"))
        for path in sorted(data_files):
            if ".tmp" in path.name:
                continue
            artifacts[f"{prior}/{path.name}"] = sha256_hex(path.read_bytes())

    provider_usage: dict[str, dict[str, int]] = {}
    for usage_stage, slot_name in _USAGE_STAGES:
        usage_meta = mf.read_meta(tree, usage_stage)
        provider_usage[slot_name] = {
            "posts": usage_meta.provider_posts,
            "cache_hits": usage_meta.provider_cache_hits,
        }

    content = release.release_record_content(
        label=label,
        preparation_version_id=preparation_version,
        pool_label=tree.pool_label,
        pool_version_id=tree.pool_version_id,
        pool_release_record_path=config.input.release_record,
        preparation_config_hash=tree.preparation_config_hash,
        config_path=str(config_path),
        image_count=len(ids),
        artifacts=artifacts,
        provider_config_hashes=provider_hashes,
        provider_usage=provider_usage,
        dev_only=config.release.dev_only,
        code_version=code_version,
        created_at=clock(),
    )
    releases_root.mkdir(parents=True, exist_ok=True)
    record_path = mf.write_release_record(releases_root, label, content)
    meta = _meta(
        tree,
        stage,
        "p08-neardup",
        image_count=len(ids),
        config_echo={"tag": config.release.tag, "dev_only": config.release.dev_only},
        provider_hashes=dict(provider_hashes),
        counters={"artifact_files": len(artifacts)},
        array_shapes={},
        provider_posts=0,
        provider_cache_hits=0,
        code_version=code_version,
    )
    _write_stage(tree, stage, meta, {})
    return meta, ReleaseFacts(preparation_version, label, record_path)


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
        image_count=meta.image_count,
        provider_posts=meta.provider_posts,
        provider_cache_hits=meta.provider_cache_hits,
        counters=meta.counters,
        skipped=skipped,
    )


def _release_facts(
    tree: PreparationTree, config: PreparationConfig, releases_root: Path
) -> ReleaseFacts:
    """Recompute the p09 facts for a resumed run - deterministic (spec 6)."""
    preparation_version = release.release_preparation_version_id(
        tree.pool_version_id, tree.preparation_config_hash
    )
    label = release.release_label(config.release.tag, preparation_version)
    record_path = releases_root / f"{label}.json"
    if not record_path.exists():
        raise mf.ManifestError(
            f"{record_path}: p09 is complete but the committed record is missing. "
            "Use --force-from p09 to write it again."
        )
    return ReleaseFacts(preparation_version, label, record_path)


def run_preparation(
    config: PreparationConfig,
    *,
    config_path: Path,
    data_root: Path,
    releases_root: Path,
    code_version: str,
    through: str | None = None,
    force_from: str | None = None,
    providers: Mapping[str, object] | None = None,
    clock: Callable[[], str] | None = None,
    report_only: bool = False,
) -> PreparationReport:
    """Run the pipeline through the requested stage. The library API.

    The release record named by the config is parsed and checked
    against the R15 rule before a tree exists. An injected providers
    mapping (slot name to instance) bypasses wiring - the test path.
    With report_only the runner executes nothing: it reads the
    complete stages and stops at the first stage that is not complete.
    """
    clock = clock if clock is not None else _utc_now_iso
    through_stage = _normalize_stage(through) if through else STAGE_NAMES[-1]

    record = mf.parse_release_record(Path(config.input.release_record))
    intake.intake_check_release(record, config.release.dev_only)

    hashes = provider_config_hashes(config, providers)
    tree = PreparationTree(
        data_root=data_root,
        pool_version_id=record.pool_version_id,
        preparation_config_hash=preparation_config_hash(config, hashes),
        pool_label=record.label,
    )

    if force_from is not None:
        start = STAGE_NAMES.index(_normalize_stage(force_from))
        for stage in STAGE_NAMES[start:]:
            directory = mf.stage_dir(tree, stage)
            if directory.exists():
                shutil.rmtree(directory)

    reports: list[StageReport] = []
    facts: ReleaseFacts | None = None

    for stage in STAGE_NAMES[: STAGE_NAMES.index(through_stage) + 1]:
        if mf.stage_is_complete(tree, stage):
            reports.append(_report_from_meta(mf.read_meta(tree, stage), skipped=True))
            if stage == "p09-release":
                facts = _release_facts(tree, config, releases_root)
            continue
        if report_only:
            break
        started = clock()
        wall_start = time.monotonic()
        meta, stage_facts = _execute_stage(
            stage, record, config, tree, config_path, releases_root, hashes,
            code_version, clock, providers,
        )
        if stage_facts is not None:
            facts = stage_facts
        _write_timings(tree, stage, started, clock(), time.monotonic() - wall_start)
        reports.append(_report_from_meta(meta, skipped=False))

    return PreparationReport(
        pool_version_id=tree.pool_version_id,
        pool_label=tree.pool_label,
        preparation_config_hash=tree.preparation_config_hash,
        stages=tuple(reports),
        preparation_version_id=None if facts is None else facts.preparation_version_id,
        release_label=None if facts is None else facts.release_label,
        release_record_path=None if facts is None else str(facts.record_path),
    )


def _execute_stage(
    stage: str,
    record: PoolReleaseRecord,
    config: PreparationConfig,
    tree: PreparationTree,
    config_path: Path,
    releases_root: Path,
    provider_hashes: Mapping[str, str],
    code_version: str,
    clock: Callable[[], str],
    providers: Mapping[str, object] | None,
) -> tuple[StageMeta, ReleaseFacts | None]:
    def provider_for(slot_name: str) -> object:
        if providers is not None and slot_name in providers:
            return providers[slot_name]
        return _wire_slot(slot_name, config, tree.data_root)

    if stage == "p00-intake":
        return run_p00_intake(record, config, tree, code_version), None
    if stage == "p01-elements":
        return run_p01_elements(provider_for("describer"), config, tree, code_version), None
    if stage == "p02-normalize":
        return run_p02_normalize(config, tree, code_version), None
    if stage == "p03-cap":
        return run_p03_cap(config, tree, code_version), None
    if stage == "p04-vocabulary":
        return (
            run_p04_vocabulary(provider_for("text_encoder"), config, tree, code_version),
            None,
        )
    if stage == "p05-linedraw":
        return (
            run_p05_linedraw(provider_for("line_drawer"), config, tree, code_version),
            None,
        )
    if stage == "p06-outline":
        return (
            run_p06_outline(provider_for("image_encoder"), config, tree, code_version),
            None,
        )
    if stage == "p07-boxes":
        return run_p07_boxes(provider_for("element_boxes"), config, tree, code_version), None
    if stage == "p08-neardup":
        return run_p08_neardup(config, tree, code_version), None
    if stage == "p09-release":
        return run_p09_release(
            config, tree, config_path, releases_root, provider_hashes, code_version, clock
        )
    raise ValueError(f"unknown stage: {stage}")


def _write_timings(
    tree: PreparationTree, stage: str, started: str, finished: str, seconds: float
) -> None:
    mf.write_json_pretty(
        mf.stage_dir(tree, stage) / "timings.json",
        {"started": started, "finished": finished, "seconds": quantize_measured(seconds)},
    )


def format_report(report: PreparationReport) -> str:
    """Text report for the command line: numbers, not adjectives."""
    lines = [
        f"pool {report.pool_label} ({report.pool_version_id[:8]})  "
        f"config c{report.preparation_config_hash[:8]}",
    ]
    for entry in report.stages:
        flag = " (reused)" if entry.skipped else ""
        counters = ", ".join(f"{k}={v}" for k, v in entry.counters) or "-"
        lines.append(
            f"{entry.stage}: images={entry.image_count} posts={entry.provider_posts} "
            f"cache_hits={entry.provider_cache_hits} counters[{counters}]{flag}"
        )
    if report.preparation_version_id is not None:
        lines.append(
            f"released {report.release_label} "
            f"preparation_version={report.preparation_version_id[:16]}"
        )
    return "\n".join(lines)
