"""Artifact I/O for the curation pipeline.

Spec: docs/specs/pool-curation.md section 11. This module owns the
curation file formats in the data root: manifests, rejections, records,
meta, and timings. The pipeline-agnostic primitives (atomic writes,
canonical JSON rows, the image store, release records) live in
pool/artifacts.py and are re-exported here. A stage directory is
complete when its meta.json exists and parses - meta.json is always the
last file a stage writes.
"""

import json
from pathlib import Path

from core.canonical import JsonValue
from pool.artifacts import (
    ManifestError,
    _dict_to_pairs,
    _pairs_to_dict,
    corpus_slug,
    image_path,
    load_image_bytes,
    read_jsonl,
    store_image_bytes,
    vector_path,
    write_bytes_atomic,
    write_json_pretty,
    write_jsonl,
    write_release_record,
)
from pool.curation.types import (
    ArtifactTree,
    CandidateRecord,
    ImageRecord,
    Rejection,
    ReviewRecord,
    StageMeta,
)

__all__ = [
    "ManifestError",
    "corpus_slug",
    "image_path",
    "load_image_bytes",
    "read_jsonl",
    "store_image_bytes",
    "vector_path",
    "write_bytes_atomic",
    "write_json_pretty",
    "write_jsonl",
    "write_release_record",
    "stage_dir",
    "stage_label",
    "candidate_to_row",
    "row_to_candidate",
    "manifest_row",
    "image_record_to_row",
    "row_to_image_record",
    "rejection_to_row",
    "row_to_rejection",
    "meta_to_json",
    "json_to_meta",
    "write_meta",
    "read_meta",
    "stage_is_complete",
    "parse_review",
]


def stage_dir(tree: ArtifactTree, stage: str) -> Path:
    return (
        tree.data_root
        / "curation"
        / tree.corpus_id[:8]
        / tree.curation_config_hash[:8]
        / stage
    )


def stage_label(tree: ArtifactTree, stage: str) -> str:
    return f"{tree.corpus_slug}-{tree.corpus_id[:8]}-c{tree.curation_config_hash[:8]}-{stage}"


def candidate_to_row(candidate: CandidateRecord) -> dict[str, JsonValue]:
    return {
        "source_key": candidate.source_key,
        "claimed_width": candidate.claimed_width,
        "claimed_height": candidate.claimed_height,
        "captions": list(candidate.captions),
        "attribution": _pairs_to_dict(candidate.attribution),
    }


def row_to_candidate(row: dict[str, JsonValue]) -> CandidateRecord:
    return CandidateRecord(
        source_key=str(row["source_key"]),
        claimed_width=None if row["claimed_width"] is None else int(row["claimed_width"]),
        claimed_height=None if row["claimed_height"] is None else int(row["claimed_height"]),
        captions=tuple(str(c) for c in row["captions"]),
        attribution=_dict_to_pairs(row["attribution"], "candidate.attribution"),
    )


def manifest_row(image_id: str, source_key: str) -> dict[str, JsonValue]:
    return {"image_id": image_id, "source_key": source_key}


def image_record_to_row(record: ImageRecord) -> dict[str, JsonValue]:
    return {
        "image_id": record.image_id,
        "source_key": record.source_key,
        "width": record.width,
        "height": record.height,
        "format": record.image_format,
        "captions": list(record.captions),
        "attribution": _pairs_to_dict(record.attribution),
    }


def row_to_image_record(row: dict[str, JsonValue]) -> ImageRecord:
    return ImageRecord(
        image_id=str(row["image_id"]),
        source_key=str(row["source_key"]),
        width=int(row["width"]),
        height=int(row["height"]),
        image_format=str(row["format"]),
        captions=tuple(str(c) for c in row["captions"]),
        attribution=_dict_to_pairs(row["attribution"], "record.attribution"),
    )


def rejection_to_row(rejection: Rejection) -> dict[str, JsonValue]:
    return {
        "key": rejection.key,
        "stage": rejection.stage,
        "reason": rejection.reason,
        "measured": rejection.measured,
        "detail": rejection.detail,
    }


def row_to_rejection(row: dict[str, JsonValue]) -> Rejection:
    return Rejection(
        key=str(row["key"]),
        stage=str(row["stage"]),
        reason=str(row["reason"]),
        measured=None if row["measured"] is None else float(row["measured"]),
        detail=str(row["detail"]),
    )


def meta_to_json(meta: StageMeta) -> dict[str, JsonValue]:
    return {
        "stage": meta.stage,
        "label": meta.label,
        "parent_stage": meta.parent_stage,
        "input_count": meta.input_count,
        "survivor_count": meta.survivor_count,
        "rejection_count": meta.rejection_count,
        "rejections_by_reason": {k: v for k, v in meta.rejections_by_reason},
        "config_echo": {k: v for k, v in meta.config_echo},
        "provider_config_hashes": _pairs_to_dict(meta.provider_config_hashes),
        "counters": {k: v for k, v in meta.counters},
        "bytes_retrieved": meta.bytes_retrieved,
        "bytes_cumulative": meta.bytes_cumulative,
        "provider_requests": meta.provider_requests,
        "code_version": meta.code_version,
    }


def json_to_meta(value: dict[str, JsonValue], where: str) -> StageMeta:
    try:
        return StageMeta(
            stage=str(value["stage"]),
            label=str(value["label"]),
            parent_stage=None if value["parent_stage"] is None else str(value["parent_stage"]),
            input_count=int(value["input_count"]),
            survivor_count=int(value["survivor_count"]),
            rejection_count=int(value["rejection_count"]),
            rejections_by_reason=tuple(
                sorted((str(k), int(v)) for k, v in value["rejections_by_reason"].items())
            ),
            config_echo=tuple(sorted(value["config_echo"].items())),
            provider_config_hashes=_dict_to_pairs(
                value["provider_config_hashes"], f"{where}.provider_config_hashes"
            ),
            counters=tuple(sorted((str(k), int(v)) for k, v in value["counters"].items())),
            bytes_retrieved=int(value["bytes_retrieved"]),
            bytes_cumulative=int(value["bytes_cumulative"]),
            provider_requests=int(value["provider_requests"]),
            code_version=str(value["code_version"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ManifestError(
            f"{where}: malformed meta.json ({error!r}). "
            "Use --force-from on this stage to compute it again."
        ) from error


def write_meta(tree: ArtifactTree, stage: str, meta: StageMeta) -> None:
    """Write meta.json for a stage. This write marks the stage complete."""
    if meta.input_count != meta.survivor_count + meta.rejection_count:
        raise ManifestError(
            f"{stage}: accounting broken before write: input {meta.input_count} != "
            f"survivors {meta.survivor_count} + rejections {meta.rejection_count}"
        )
    write_json_pretty(stage_dir(tree, stage) / "meta.json", meta_to_json(meta))


def read_meta(tree: ArtifactTree, stage: str) -> StageMeta:
    path = stage_dir(tree, stage) / "meta.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ManifestError(f"{path}: cannot read: {error}") from error
    except json.JSONDecodeError as error:
        raise ManifestError(
            f"{path}: malformed meta.json ({error}). "
            "Use --force-from on this stage to compute it again."
        ) from error
    return json_to_meta(raw, str(path))


def stage_is_complete(tree: ArtifactTree, stage: str) -> bool:
    """The check that the stage directory has a parseable meta.json.

    A missing file means the stage is not complete. A file that exists
    but does not parse raises - a silent recompute can hide corruption
    (R14).
    """
    if not (stage_dir(tree, stage) / "meta.json").exists():
        return False
    read_meta(tree, stage)
    return True


def parse_review(raw: object, source: str) -> ReviewRecord:
    """Strict parse of review.json. See spec section 10, s08."""
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: expected an object")
    unknown = set(raw) - {"verdict", "reviewer", "date", "notes"}
    if unknown:
        raise ManifestError(f"{source}: unknown field(s): {sorted(unknown)}")
    try:
        record = ReviewRecord(
            verdict=str(raw["verdict"]),
            reviewer=str(raw["reviewer"]),
            date=str(raw["date"]),
            notes=str(raw["notes"]),
        )
    except KeyError as error:
        raise ManifestError(f"{source}: missing field {error}") from error
    if record.verdict not in ("pass", "fail"):
        raise ManifestError(f'{source}: verdict must be "pass" or "fail"')
    if not record.reviewer or not record.date:
        raise ManifestError(f"{source}: reviewer and date must not be empty")
    return record
