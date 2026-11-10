"""Shared artifact I/O primitives for the pool pipelines.

Spec: docs/specs/pool-curation.md section 11 and
docs/specs/pool-preparation.md section 13. This module owns the
pipeline-agnostic file primitives: atomic writes, canonical JSON rows,
the content-addressed image store, the vector cache paths, and release
records. Formats that belong to one pipeline (stage directories, meta
files, row codecs) stay in that pipeline's own manifest module.
"""

import json
import os
import re
from pathlib import Path
from typing import Iterable

from core.canonical import JsonValue, canonical_json, canonical_json_pretty, sha256_hex


class ManifestError(ValueError):
    """A stored artifact did not parse or reconcile."""


def corpus_slug(repo_id: str) -> str:
    """Short human-readable corpus name for labels and paths."""
    last = repo_id.rsplit("/", 1)[-1].lower()
    return re.sub(r"[^a-z0-9_]", "-", last)


def image_path(data_root: Path, image_id: str) -> Path:
    return data_root / "images" / "raw" / image_id[:2] / image_id


def vector_path(data_root: Path, encoder_config_hash: str, image_id: str) -> Path:
    return (
        data_root / "cache" / "vectors" / encoder_config_hash[:8] / image_id[:2]
        / f"{image_id}.npy"
    )


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write bytes through a temporary sibling, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_jsonl(path: Path, rows: Iterable[dict[str, JsonValue]]) -> None:
    text = "".join(canonical_json(row) + "\n" for row in rows)
    write_bytes_atomic(path, text.encode("utf-8"))


def read_jsonl(path: Path) -> list[dict[str, JsonValue]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ManifestError(f"{path}: cannot read: {error}") from error
    rows: list[dict[str, JsonValue]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ManifestError(f"{path}:{number}: bad JSON row: {error}") from error
    return rows


def read_journal(path: Path) -> list[dict[str, JsonValue]]:
    """Read an append journal: one JSON row for each complete line.

    A file that is not there gives no rows. A stop in the middle of an
    append can put a part of one row at the end of the file. That part
    has no line end, thus it is not a row: this function removes it
    from the file, and the next append starts on a line boundary. A
    complete line that does not parse raises - that is damage, not a
    stop (R14).
    """
    if not path.exists():
        return []
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ManifestError(f"{path}: cannot read: {error}") from error
    complete = data[: data.rfind(b"\n") + 1]
    if len(complete) != len(data):
        with path.open("r+b") as handle:
            handle.truncate(len(complete))
            handle.flush()
            os.fsync(handle.fileno())
    rows: list[dict[str, JsonValue]] = []
    for number, line in enumerate(complete.decode("utf-8").splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ManifestError(f"{path}:{number}: bad JSON row: {error}") from error
    return rows


def append_journal(path: Path, row: dict[str, JsonValue]) -> None:
    """Add one row to an append journal and put it on the disk.

    The row is on the disk before this function ends, thus a stop
    after that cannot remove it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write((canonical_json(row) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())


def write_json_pretty(path: Path, value: JsonValue) -> None:
    write_bytes_atomic(path, (canonical_json_pretty(value) + "\n").encode("utf-8"))


def _pairs_to_dict(pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return {k: v for k, v in pairs}


def _dict_to_pairs(value: object, where: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        raise ManifestError(f"{where}: expected an object")
    return tuple(sorted((str(k), str(v)) for k, v in value.items()))


def store_image_bytes(data_root: Path, image_bytes: bytes) -> str:
    """Store bytes content-addressed. Returns the image_id."""
    image_id = sha256_hex(image_bytes)
    path = image_path(data_root, image_id)
    if not path.exists():
        write_bytes_atomic(path, image_bytes)
    return image_id


def load_image_bytes(data_root: Path, image_id: str) -> bytes:
    """Read stored bytes. A missing image raises - no fallback (R14)."""
    path = image_path(data_root, image_id)
    try:
        return path.read_bytes()
    except OSError as error:
        raise ManifestError(f"{path}: image bytes absent from the store: {error}") from error


def write_release_record(releases_root: Path, label: str, content: dict[str, JsonValue]) -> Path:
    """Write the committed release record file (R11)."""
    path = releases_root / f"{label}.json"
    write_json_pretty(path, content)
    return path
