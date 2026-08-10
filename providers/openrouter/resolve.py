"""POST-body construction and cache-first resolution for the chat slots.

Spec: docs/specs/pool-curation.md section 8a and
docs/specs/pool-preparation.md section 8. Each chat slot builds one
POST body for each work item, parses and validates the response at the
boundary, and caches it with the item key and the provider config_hash
in the path (R12). This module owns the logic that all chat slots
share. The slot modules own their schemas and parsers.
"""

import base64
import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from core.canonical import JsonValue
from providers.openrouter.cache import load_cached_response, response_cache_path, store_response
from providers.openrouter.client import OpenRouterClient
from providers.openrouter.errors import OpenRouterResponseError

RESPONSE_FORMAT_MODES = ("json_schema", "json_object")


class _ChatSlotParams(Protocol):
    """The POST parameters that all chat slot configs contain."""

    @property
    def slot(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def temperature(self) -> float: ...

    @property
    def seed(self) -> int: ...

    @property
    def max_tokens(self) -> int: ...

    @property
    def reasoning_enabled(self) -> bool: ...

    @property
    def response_format_mode(self) -> str: ...


def checked_response_format_mode(mode: str) -> str:
    """The mode unchanged. An unknown mode raises ValueError."""
    if mode not in RESPONSE_FORMAT_MODES:
        raise ValueError(
            f"response_format_mode must be one of {RESPONSE_FORMAT_MODES}, got {mode!r}"
        )
    return mode


def default_clock() -> str:
    """The UTC time in ISO 8601 text - the created_at value for new entries."""
    return datetime.now(timezone.utc).isoformat()


def data_uri(image_bytes: bytes) -> str:
    """The base64 data URI, with the mime type read from magic bytes."""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif image_bytes.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    elif image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    else:
        raise OpenRouterResponseError(
            "unknown image magic bytes: PNG, JPEG, WEBP, and GIF are supported"
        )
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def response_format_value(
    config: _ChatSlotParams, schema: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    """The response_format field for the configured mode."""
    if config.response_format_mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": config.slot, "strict": True, "schema": schema},
    }


def chat_request_body(
    config: _ChatSlotParams,
    instruction: str,
    image_bytes: bytes,
    schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """The chat-completions POST body for one image."""
    return {
        "model": config.model,
        "temperature": config.temperature,
        "seed": config.seed,
        "max_tokens": config.max_tokens,
        "reasoning": {"enabled": config.reasoning_enabled},
        "response_format": response_format_value(config, schema),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": data_uri(image_bytes)}},
                ],
            }
        ],
    }


def text_request_body(
    config: _ChatSlotParams,
    instruction: str,
    schema: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """The chat-completions POST body for one text-only instruction.

    The generalization slot sends no image (spec P4 section 8.2).
    Everything else — model, sampling values, response format — follows
    chat_request_body.
    """
    return {
        "model": config.model,
        "temperature": config.temperature,
        "seed": config.seed,
        "max_tokens": config.max_tokens,
        "reasoning": {"enabled": config.reasoning_enabled},
        "response_format": response_format_value(config, schema),
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": instruction}],
            }
        ],
    }


def content_text(response_body: object) -> str:
    """The assistant message content string, or a boundary error."""
    try:
        content = response_body["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as error:
        raise OpenRouterResponseError(
            f"response body has no message content: {error!r}"
        ) from error
    if not isinstance(content, str):
        raise OpenRouterResponseError("message content is not a string")
    return content


def strip_one_fence(text: str) -> str:
    """Remove one Markdown fence wrapper, and nothing else."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```") and "\n" in stripped:
        head_end = stripped.index("\n")
        stripped = stripped[head_end + 1 : -3].strip()
    return stripped


def json_payload(response_body: object) -> dict[str, object]:
    """The message content parsed as one JSON object."""
    text = strip_one_fence(content_text(response_body))
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenRouterResponseError(f"message content is not JSON: {error}") from error
    if not isinstance(value, dict):
        raise OpenRouterResponseError("message content is not a JSON object")
    return value


def resolve_chat[T](
    keys: Sequence[str],
    names: Sequence[str],
    body_at: Callable[[int], dict[str, JsonValue]],
    parse: Callable[[object], T],
    config_hash: str,
    model: str,
    client: OpenRouterClient,
    cache_root: Path,
    clock: Callable[[], str],
    entry_extra_at: Callable[[int], dict[str, JsonValue]] | None = None,
) -> tuple[list[T], int]:
    """Cache-first resolution of one parsed value for each work item.

    keys are the cache keys, and names are the item names for error
    text. The two sequences are index-aligned. A cache hit is
    re-validated through the same parser, and a bad cached body
    raises. A cache miss becomes one POST with the body_at(index)
    body, and the validated response is then stored - with the
    entry_extra_at(index) fields merged in when that callable is not
    None. The output rows are index-aligned with keys. The second
    output is the cache hit count.
    """
    paths = [response_cache_path(cache_root, config_hash, key) for key in keys]
    values: list[T | None] = [None] * len(keys)
    cache_hits = 0
    miss_indexes: list[int] = []
    miss_bodies: list[dict[str, JsonValue]] = []
    for index, path in enumerate(paths):
        entry = load_cached_response(path)
        if entry is None:
            miss_indexes.append(index)
            miss_bodies.append(body_at(index))
            continue
        if "response_body" not in entry:
            raise OpenRouterResponseError(f"{path}: cache entry has no response_body")
        try:
            values[index] = parse(entry["response_body"])
        except OpenRouterResponseError as error:
            raise OpenRouterResponseError(f"cached image {names[index]}: {error}") from error
        cache_hits += 1
    if miss_indexes:
        responses = client.map_requests(miss_bodies)
        for index, response_body in zip(miss_indexes, responses, strict=True):
            try:
                value = parse(response_body)
            except OpenRouterResponseError as error:
                raise OpenRouterResponseError(
                    f"image {names[index]} (model {model}): {error}"
                ) from error
            entry = {
                "key": keys[index],
                "config_hash": config_hash,
                "model": model,
                "response_body": response_body,
                "usage": response_body.get("usage"),
                "created_at": clock(),
            }
            if entry_extra_at is not None:
                entry.update(entry_extra_at(index))
            store_response(paths[index], entry)
            values[index] = value
    return [value for value in values], cache_hits  # type: ignore[misc]
