"""OpenRouter-backed slot providers: the classifier and two estimators.

Spec: docs/specs/pool-curation.md sections 8 and 8a. Each provider
sends one POST for each image, with temperature 0, a fixed instruction
template, and a fixed JSON output format. Responses are parsed and
validated at the boundary, and cached with the image hash and the
provider config_hash in the path (R12). A response that does not
parse, or a fraction out of [0, 1], raises (R14).
"""

import base64
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import FloatArray
from providers.openrouter.cache import load_cached_response, response_cache_path, store_response
from providers.openrouter.client import OpenRouterClient
from providers.openrouter.errors import OpenRouterResponseError

TEMPERATURE = 0.0
SEED = 0
MAX_TOKENS = 512
REASONING_ENABLED = False

_RESPONSE_FORMAT_MODES = ("json_schema", "json_object")
_LABEL_PLACEHOLDER = "{label_phrases}"


class OpenRouterSlotConfig(NamedTuple):
    """The full parameter set of one OpenRouter slot.

    slot_config_hash covers all fields - a change to one of them moves
    the cache tree (R12). The API key is not a field here and is not
    part of the hash.
    """

    slot: str
    model: str
    template: str
    temperature: float
    seed: int
    max_tokens: int
    reasoning_enabled: bool
    response_format_mode: str
    probability_sum_tolerance: float | None


def slot_config_hash(config: OpenRouterSlotConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the config.

    The hash input includes the tolerance field, also when it is
    None. The API key is not part of the input.
    """
    return sha256_hex(canonical_json(dict(config._asdict())))


def _checked_slot_config(config: OpenRouterSlotConfig) -> OpenRouterSlotConfig:
    if config.response_format_mode not in _RESPONSE_FORMAT_MODES:
        raise ValueError(
            f"response_format_mode must be one of {_RESPONSE_FORMAT_MODES}, "
            f"got {config.response_format_mode!r}"
        )
    return config


def _default_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data_uri(image_bytes: bytes) -> str:
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


def _response_format(
    config: OpenRouterSlotConfig, schema: dict[str, JsonValue]
) -> dict[str, JsonValue]:
    if config.response_format_mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": config.slot, "strict": True, "schema": schema},
    }


def _request_body(
    config: OpenRouterSlotConfig,
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
        "response_format": _response_format(config, schema),
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": _data_uri(image_bytes)}},
                ],
            }
        ],
    }


def _fraction_schema(json_key: str) -> dict[str, JsonValue]:
    return {
        "type": "object",
        "properties": {json_key: {"type": "number", "minimum": 0, "maximum": 1}},
        "required": [json_key],
        "additionalProperties": False,
    }


def _choice_schema(phrases: tuple[str, ...]) -> dict[str, JsonValue]:
    """One selected category plus a confidence.

    The enum constrains the label to the requested set at the model
    side, thus an out-of-set answer cannot occur in strict schema
    mode. An eight-number contract was here before, and it broke in
    live runs: a fast model does not reliably emit numbers that sum
    to 1.
    """
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": list(phrases)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["label", "confidence"],
        "additionalProperties": False,
    }


def _content_text(response_body: object) -> str:
    try:
        content = response_body["choices"][0]["message"]["content"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError) as error:
        raise OpenRouterResponseError(
            f"response body has no message content: {error!r}"
        ) from error
    if not isinstance(content, str):
        raise OpenRouterResponseError("message content is not a string")
    return content


def _strip_one_fence(text: str) -> str:
    """Remove one Markdown fence wrapper, and nothing else."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```") and "\n" in stripped:
        head_end = stripped.index("\n")
        stripped = stripped[head_end + 1 : -3].strip()
    return stripped


def _json_payload(response_body: object) -> dict[str, object]:
    text = _strip_one_fence(_content_text(response_body))
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise OpenRouterResponseError(f"message content is not JSON: {error}") from error
    if not isinstance(value, dict):
        raise OpenRouterResponseError("message content is not a JSON object")
    return value


def _fraction_value(payload: Mapping[str, object], json_key: str) -> float:
    """One numeric fraction in [0, 1]. Not clamped - a violation raises."""
    if json_key not in payload:
        raise OpenRouterResponseError(f"response JSON has no {json_key!r} field")
    value = payload[json_key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpenRouterResponseError(f"{json_key} is not a number: {value!r}")
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise OpenRouterResponseError(f"{json_key} is out of [0, 1]: {number}")
    return number


def _choice_row(
    payload: Mapping[str, object], phrases: tuple[str, ...]
) -> tuple[float, ...]:
    """The probability row for one selected label, in phrase sequence.

    The winner cell holds the confidence. The remaining mass spreads
    equally on the other labels, thus the row sums to 1 and the
    protocol contract holds. The confidence must be more than 1/L, or
    the stated label could not be the argmax of its own row - that
    answer is contradictory and raises (R14).
    """
    if "label" not in payload or "confidence" not in payload:
        raise OpenRouterResponseError('response JSON needs "label" and "confidence"')
    label = payload["label"]
    if not isinstance(label, str) or label not in phrases:
        raise OpenRouterResponseError(f"label {label!r} is not in the requested set")
    raw = payload["confidence"]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise OpenRouterResponseError(f"confidence is not a number: {raw!r}")
    confidence = float(raw)
    if not 0.0 <= confidence <= 1.0:
        raise OpenRouterResponseError(f"confidence is out of [0, 1]: {confidence}")
    count = len(phrases)
    if count > 1 and confidence * count <= 1.0:
        raise OpenRouterResponseError(
            f"confidence {confidence} for {label!r} is at or below 1/{count} - "
            "the stated label would not win its own row"
        )
    if count == 1:
        return (1.0,)
    rest = (1.0 - confidence) / (count - 1)
    return tuple(confidence if phrase == label else rest for phrase in phrases)


def _resolved_values[T](
    images: Sequence[bytes],
    parse: Callable[[object], T],
    body_for_image: Callable[[bytes], dict[str, JsonValue]],
    config_hash: str,
    model: str,
    client: OpenRouterClient,
    cache_root: Path,
    clock: Callable[[], str],
) -> tuple[list[T], int]:
    """Cache-first resolution of one parsed value for each image.

    A cache hit is re-validated through the same parser, and a bad
    cached body raises. A cache miss becomes one POST, and the
    validated response is then stored. The output rows are
    index-aligned with images. The second output is the cache hit
    count.
    """
    keys = [sha256_hex(image) for image in images]
    paths = [response_cache_path(cache_root, config_hash, key) for key in keys]
    values: list[T | None] = [None] * len(images)
    cache_hits = 0
    miss_indexes: list[int] = []
    miss_bodies: list[dict[str, JsonValue]] = []
    for index, path in enumerate(paths):
        entry = load_cached_response(path)
        if entry is None:
            miss_indexes.append(index)
            miss_bodies.append(body_for_image(images[index]))
            continue
        if "response_body" not in entry:
            raise OpenRouterResponseError(f"{path}: cache entry has no response_body")
        try:
            values[index] = parse(entry["response_body"])
        except OpenRouterResponseError as error:
            raise OpenRouterResponseError(f"cached image {keys[index]}: {error}") from error
        cache_hits += 1
    if miss_indexes:
        responses = client.map_requests(miss_bodies)
        for index, response_body in zip(miss_indexes, responses, strict=True):
            try:
                value = parse(response_body)
            except OpenRouterResponseError as error:
                raise OpenRouterResponseError(
                    f"image {keys[index]} (model {model}): {error}"
                ) from error
            entry = {
                "key": keys[index],
                "config_hash": config_hash,
                "model": model,
                "response_body": response_body,
                "usage": response_body.get("usage"),
                "created_at": clock(),
            }
            store_response(paths[index], entry)
            values[index] = value
    return [value for value in values], cache_hits  # type: ignore[misc]


def _fraction_values(
    images: Sequence[bytes],
    slot_config: OpenRouterSlotConfig,
    json_key: str,
    client: OpenRouterClient,
    cache_root: Path,
    clock: Callable[[], str],
) -> tuple[list[float], int]:
    schema = _fraction_schema(json_key)

    def body_for_image(image_bytes: bytes) -> dict[str, JsonValue]:
        return _request_body(slot_config, slot_config.template, image_bytes, schema)

    def parse(response_body: object) -> float:
        return _fraction_value(_json_payload(response_body), json_key)

    return _resolved_values(
        images,
        parse,
        body_for_image,
        slot_config_hash(slot_config),
        slot_config.model,
        client,
        cache_root,
        clock,
    )


class OpenRouterTextCoverageEstimator:
    """TextCoverageEstimator through OpenRouter - the s03 slot."""

    _JSON_KEY = "text_area_fraction"

    def __init__(
        self,
        slot_config: OpenRouterSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._slot_config = _checked_slot_config(slot_config)
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else _default_clock
        self._config_hash = slot_config_hash(slot_config)
        self._cache_hit_count = 0

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def cache_hit_count(self) -> int:
        return self._cache_hit_count

    @property
    def post_count(self) -> int:
        return self._client.post_count

    def estimate_text_coverage(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), each value in [0, 1]."""
        values, hits = _fraction_values(
            images, self._slot_config, self._JSON_KEY,
            self._client, self._cache_root, self._clock,
        )
        self._cache_hit_count += hits
        return np.asarray(values, dtype=np.float32)


class OpenRouterSalientObjectEstimator:
    """SalientObjectEstimator through OpenRouter - the s05 slot."""

    _JSON_KEY = "largest_object_fraction"

    def __init__(
        self,
        slot_config: OpenRouterSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._slot_config = _checked_slot_config(slot_config)
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else _default_clock
        self._config_hash = slot_config_hash(slot_config)
        self._cache_hit_count = 0

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def cache_hit_count(self) -> int:
        return self._cache_hit_count

    @property
    def post_count(self) -> int:
        return self._client.post_count

    def estimate_salient_object_fraction(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), each value in [0, 1]."""
        values, hits = _fraction_values(
            images, self._slot_config, self._JSON_KEY,
            self._client, self._cache_root, self._clock,
        )
        self._cache_hit_count += hits
        return np.asarray(values, dtype=np.float32)


class OpenRouterZeroShotImageClassifier:
    """ZeroShotImageClassifier through OpenRouter - the s04 slot.

    The instruction template must contain the {label_phrases}
    placeholder. The provider replaces it verbatim with the quoted
    label phrases. The cache path holds the image hash plus the
    provider config_hash only - a cached body for a different phrase
    set does not validate and raises.
    """

    def __init__(
        self,
        slot_config: OpenRouterSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
    ) -> None:
        checked = _checked_slot_config(slot_config)
        if _LABEL_PLACEHOLDER not in checked.template:
            raise ValueError(
                f"classifier instruction template must contain {_LABEL_PLACEHOLDER!r}"
            )
        self._slot_config = checked
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else _default_clock
        self._config_hash = slot_config_hash(slot_config)
        self._cache_hit_count = 0

    @property
    def config_hash(self) -> str:
        return self._config_hash

    @property
    def cache_hit_count(self) -> int:
        return self._cache_hit_count

    @property
    def post_count(self) -> int:
        return self._client.post_count

    def classify(self, images: Sequence[bytes], labels: Sequence[str]) -> FloatArray:
        """The output is float32 (B, L) in label sequence. Each row sums to 1."""
        phrases = tuple(labels)
        quoted = '"' + '", "'.join(phrases) + '"'
        instruction = self._slot_config.template.replace(_LABEL_PLACEHOLDER, quoted)
        schema = _choice_schema(phrases)

        def body_for_image(image_bytes: bytes) -> dict[str, JsonValue]:
            return _request_body(self._slot_config, instruction, image_bytes, schema)

        def parse(response_body: object) -> tuple[float, ...]:
            return _choice_row(_json_payload(response_body), phrases)

        values, hits = _resolved_values(
            images,
            parse,
            body_for_image,
            self._config_hash,
            self._slot_config.model,
            self._client,
            self._cache_root,
            self._clock,
        )
        self._cache_hit_count += hits
        if not values:
            return np.zeros((0, len(phrases)), dtype=np.float32)
        return np.asarray(values, dtype=np.float32)
