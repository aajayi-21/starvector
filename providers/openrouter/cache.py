"""Response cache for the OpenRouter providers.

Spec: docs/specs/pool-curation.md section 8a and R12. Each response is
stored as pretty canonical JSON in the data root, with the provider
config_hash and the image hash in the file path. Re-runs and resume
read the cache and get the same bytes.
"""

import json
import os
import threading
from pathlib import Path

from core.canonical import JsonValue, canonical_json_pretty
from providers.openrouter.errors import OpenRouterResponseError

def response_cache_path(cache_root: Path, config_hash: str, key: str) -> Path:
    """The cache file path for one response entry."""
    return cache_root / config_hash[:8] / key[:2] / (key + ".json")


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Write bytes through a temporary sibling file, then rename.

    This helper stays local because providers do not import pool
    code. The sibling name is one-writer-unique: two concurrent
    writes of one key - two practice scores of one sketch, or two
    players with one drawing - each rename their own file, and the
    last writer wins with equal content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def load_cached_response(path: Path) -> dict[str, JsonValue] | None:
    """Read one cache entry. A missing file gives None.

    A file that exists but does not parse raises
    OpenRouterResponseError (R14) - a silent recompute can hide
    corruption.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenRouterResponseError(f"{path}: cache entry does not parse: {error}") from error
    if not isinstance(value, dict):
        raise OpenRouterResponseError(f"{path}: cache entry is not a JSON object")
    return value


def store_response(path: Path, entry: dict[str, JsonValue]) -> None:
    """Write one cache entry as pretty canonical JSON, atomic."""
    _write_bytes_atomic(path, (canonical_json_pretty(entry) + "\n").encode("utf-8"))
