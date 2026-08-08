"""Artifact I/O for the preparation pipeline.

Spec: docs/specs/pool-preparation.md section 11. This module owns the
preparation file formats in the data root: stage rows, arrays, meta,
and timings. The pipeline-agnostic primitives (atomic writes, canonical
JSON rows, the image store, release records) live in pool/artifacts.py
and are re-exported here. A stage directory is complete when its
meta.json exists and parses - meta.json is always the last file a
stage writes.
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from core.canonical import JsonValue, quantize_measured
from pool.artifacts import (
    ManifestError,
    _dict_to_pairs,
    _pairs_to_dict,
    image_path,
    load_image_bytes,
    read_jsonl,
    vector_path,
    write_bytes_atomic,
    write_json_pretty,
    write_jsonl,
    write_release_record,
)
from pool.preparation.stages.intake import intake_parse_release_record
from pool.preparation.types import (
    Box,
    CutRecord,
    ElementResponse,
    GroupRow,
    IntakeRecord,
    PoolReleaseRecord,
    PreparationTree,
    StageMeta,
)

__all__ = [
    "ManifestError",
    "image_path",
    "load_image_bytes",
    "read_jsonl",
    "vector_path",
    "write_bytes_atomic",
    "write_json_pretty",
    "write_jsonl",
    "write_release_record",
    "stage_dir",
    "stage_label",
    "linedraw_path",
    "save_npy_atomic",
    "intake_record_to_row",
    "row_to_intake_record",
    "element_row",
    "row_to_element_response",
    "element_list_row",
    "row_to_element_list",
    "cut_to_row",
    "vocabulary_row",
    "drawing_row",
    "box_row",
    "group_to_row",
    "row_to_group",
    "meta_to_json",
    "json_to_meta",
    "write_meta",
    "read_meta",
    "stage_is_complete",
    "parse_release_record",
]


def stage_dir(tree: PreparationTree, stage: str) -> Path:
    return (
        tree.data_root
        / "preparation"
        / tree.pool_version_id[:8]
        / tree.preparation_config_hash[:8]
        / stage
    )


def stage_label(tree: PreparationTree, stage: str) -> str:
    return f"{tree.pool_label}-c{tree.preparation_config_hash[:8]}-{stage}"


def linedraw_path(data_root: Path, line_drawer_hash: str, image_id: str) -> Path:
    """The image-level line-drawing cache path (spec section 11)."""
    return (
        data_root / "images" / "linedraw" / line_drawer_hash[:8] / image_id[:2]
        / f"{image_id}.png"
    )


def save_npy_atomic(path: Path, array: np.ndarray) -> None:
    """Write one .npy file through a temporary sibling, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp.npy")
    np.save(tmp, array)
    os.replace(tmp, path)


def intake_record_to_row(record: IntakeRecord) -> dict[str, JsonValue]:
    return {
        "image_id": record.image_id,
        "width": record.width,
        "height": record.height,
        "format": record.image_format,
    }


def row_to_intake_record(row: dict[str, JsonValue]) -> IntakeRecord:
    return IntakeRecord(
        image_id=str(row["image_id"]),
        width=int(row["width"]),
        height=int(row["height"]),
        image_format=str(row["format"]),
    )


def element_row(image_id: str, response: ElementResponse) -> dict[str, JsonValue]:
    """One p01 elements.jsonl row: the structured R2 response."""
    return {
        "image_id": image_id,
        "objects": list(response.objects),
        "materials": list(response.materials),
        "colors": list(response.colors),
        "shapes": list(response.shapes),
        "scale": response.scale,
        "setting": response.setting,
        "ambience": list(response.ambience),
    }


def row_to_element_response(row: dict[str, JsonValue]) -> tuple[str, ElementResponse]:
    return str(row["image_id"]), ElementResponse(
        objects=tuple(str(v) for v in row["objects"]),
        materials=tuple(str(v) for v in row["materials"]),
        colors=tuple(str(v) for v in row["colors"]),
        shapes=tuple(str(v) for v in row["shapes"]),
        scale=str(row["scale"]),
        setting=str(row["setting"]),
        ambience=tuple(str(v) for v in row["ambience"]),
    )


def element_list_row(image_id: str, elements: tuple[str, ...]) -> dict[str, JsonValue]:
    """One p02 normalized.jsonl or p03 capped.jsonl row."""
    return {"image_id": image_id, "elements": list(elements)}


def row_to_element_list(row: dict[str, JsonValue]) -> tuple[str, tuple[str, ...]]:
    return str(row["image_id"]), tuple(str(v) for v in row["elements"])


def cut_to_row(cut: CutRecord) -> dict[str, JsonValue]:
    return {
        "image_id": cut.image_id,
        "element": cut.element,
        "df": cut.df,
        "capping_rarity": cut.capping_rarity,
    }


def vocabulary_row(index: int, element: str, pool_frequency: int) -> dict[str, JsonValue]:
    return {"index": index, "element": element, "pool_frequency": pool_frequency}


def drawing_row(image_id: str, line_drawing_key: str, byte_count: int) -> dict[str, JsonValue]:
    return {"image_id": image_id, "line_drawing_key": line_drawing_key,
            "byte_count": byte_count}


def box_row(image_id: str, boxes: Mapping[str, Box | None]) -> dict[str, JsonValue]:
    """One p07 boxes.jsonl row. Box values are quantized measured floats."""
    encoded: dict[str, JsonValue] = {}
    for element, box in boxes.items():
        if box is None:
            encoded[element] = None
        else:
            encoded[element] = [quantize_measured(value) for value in box]
    return {"image_id": image_id, "boxes": encoded}


def group_to_row(group: GroupRow) -> dict[str, JsonValue]:
    return {
        "image_id": group.image_id,
        "group_id": group.group_id,
        "member_count": group.member_count,
    }


def row_to_group(row: dict[str, JsonValue]) -> GroupRow:
    """The inverse of group_to_row, for the scoring context loader."""
    return GroupRow(
        image_id=str(row["image_id"]),
        group_id=str(row["group_id"]),
        member_count=int(row["member_count"]),
    )


def meta_to_json(meta: StageMeta) -> dict[str, JsonValue]:
    return {
        "stage": meta.stage,
        "label": meta.label,
        "parent_stage": meta.parent_stage,
        "image_count": meta.image_count,
        "config_echo": {k: v for k, v in meta.config_echo},
        "provider_config_hashes": _pairs_to_dict(meta.provider_config_hashes),
        "counters": {k: v for k, v in meta.counters},
        "array_shapes": {k: list(v) for k, v in meta.array_shapes},
        "provider_posts": meta.provider_posts,
        "provider_cache_hits": meta.provider_cache_hits,
        "code_version": meta.code_version,
    }


def json_to_meta(value: dict[str, JsonValue], where: str) -> StageMeta:
    try:
        return StageMeta(
            stage=str(value["stage"]),
            label=str(value["label"]),
            parent_stage=None if value["parent_stage"] is None else str(value["parent_stage"]),
            image_count=int(value["image_count"]),
            config_echo=tuple(sorted(value["config_echo"].items())),
            provider_config_hashes=_dict_to_pairs(
                value["provider_config_hashes"], f"{where}.provider_config_hashes"
            ),
            counters=tuple(sorted((str(k), int(v)) for k, v in value["counters"].items())),
            array_shapes=tuple(
                sorted(
                    (str(k), tuple(int(d) for d in v))
                    for k, v in value["array_shapes"].items()
                )
            ),
            provider_posts=int(value["provider_posts"]),
            provider_cache_hits=int(value["provider_cache_hits"]),
            code_version=str(value["code_version"]),
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ManifestError(
            f"{where}: malformed meta.json ({error!r}). "
            "Use --force-from on this stage to compute it again."
        ) from error


def write_meta(tree: PreparationTree, stage: str, meta: StageMeta) -> None:
    """Write meta.json for a stage. This write marks the stage complete."""
    write_json_pretty(stage_dir(tree, stage) / "meta.json", meta_to_json(meta))


def read_meta(tree: PreparationTree, stage: str) -> StageMeta:
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


def stage_is_complete(tree: PreparationTree, stage: str) -> bool:
    """The check that the stage directory has a parseable meta.json.

    A missing file means the stage is not complete. A file that exists
    but does not parse raises - a silent recompute can hide corruption
    (R14).
    """
    if not (stage_dir(tree, stage) / "meta.json").exists():
        return False
    read_meta(tree, stage)
    return True


def parse_release_record(path: Path) -> PoolReleaseRecord:
    """Read and parse one committed P1a release record (spec section 7).

    The pure parse lives in pool/preparation/stages/intake.py - this
    wrapper only reads the file and reports read problems (R14).
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ManifestError(f"{path}: cannot read release record: {error}") from error
    except json.JSONDecodeError as error:
        raise ManifestError(f"{path}: malformed release record: {error}") from error
    return intake_parse_release_record(raw, source=str(path))
