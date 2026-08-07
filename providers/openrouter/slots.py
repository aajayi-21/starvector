"""OpenRouter-backed slot providers: the classifier and two estimators.

Spec: docs/specs/pool-curation.md sections 8 and 8a. Each provider
sends one POST for each image, with temperature 0, a fixed instruction
template, and a fixed JSON output format. Responses are parsed and
validated at the boundary, and cached with the image hash and the
provider config_hash in the path (R12). A response that does not
parse, or a fraction out of [0, 1], raises (R14). The shared POST-body
and cache machinery lives in providers/openrouter/resolve.py.
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import FloatArray
from providers.openrouter.client import OpenRouterClient
from providers.openrouter.errors import OpenRouterResponseError
from providers.openrouter.resolve import (
    chat_request_body,
    checked_response_format_mode,
    default_clock,
    json_payload,
    resolve_chat,
)

TEMPERATURE = 0.0
SEED = 0
MAX_TOKENS = 512
REASONING_ENABLED = False

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
    checked_response_format_mode(config.response_format_mode)
    return config


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
    """Cache-first resolution keyed and named by the image hash.

    Thin wrapper: resolve_chat does the work, with the SHA-256 hex
    digest of each image as the cache key and the error-text name.
    """
    keys = [sha256_hex(image) for image in images]

    def body_at(index: int) -> dict[str, JsonValue]:
        return body_for_image(images[index])

    return resolve_chat(
        keys, keys, body_at, parse, config_hash, model, client, cache_root, clock
    )


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
        return chat_request_body(slot_config, slot_config.template, image_bytes, schema)

    def parse(response_body: object) -> float:
        return _fraction_value(json_payload(response_body), json_key)

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
        self._clock = clock if clock is not None else default_clock
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
        self._clock = clock if clock is not None else default_clock
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
        self._clock = clock if clock is not None else default_clock
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
            return chat_request_body(self._slot_config, instruction, image_bytes, schema)

        def parse(response_body: object) -> tuple[float, ...]:
            return _choice_row(json_payload(response_body), phrases)

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
