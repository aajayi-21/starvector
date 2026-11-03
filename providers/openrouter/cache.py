"""Response cache for the OpenRouter providers.

Spec: docs/specs/pool-curation.md section 8a and R12. The files follow
providers/response_cache.py. This module binds the error type of the
OpenRouter providers.
"""

from pathlib import Path

from core.canonical import JsonValue
from providers import response_cache
from providers.openrouter.errors import OpenRouterResponseError
from providers.response_cache import response_cache_path, store_response

__all__ = ["load_cached_response", "response_cache_path", "store_response"]


def load_cached_response(path: Path) -> dict[str, JsonValue] | None:
    """Read one cache entry. A missing file gives None.

    A file that exists but does not parse raises
    OpenRouterResponseError (R14) - a silent recompute can hide
    corruption.
    """
    return response_cache.load_cached_response(path, OpenRouterResponseError)
