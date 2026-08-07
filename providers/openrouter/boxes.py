"""OpenRouter ElementBoxDetector - the p07 element box slot.

Spec: docs/specs/pool-preparation.md section 8 and decision D10. One
POST for each image, with that image's queried element strings in the
instruction and a strict JSON output format: one box or null for each
element. The response cache key covers the queried element list, thus
a query change makes a new entry (spec P1b section 6). A box out of
range raises (R14). Null records "not located" and is a permitted
answer, not an error.
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from core.canonical import JsonValue, canonical_json, sha256_hex
from providers.openrouter.client import OpenRouterClient
from providers.openrouter.errors import OpenRouterResponseError
from providers.openrouter.resolve import (
    chat_request_body,
    checked_response_format_mode,
    default_clock,
    json_payload,
    resolve_chat,
)
from providers.protocols import Box

BOXES_MAX_TOKENS = 1024

_ELEMENT_PLACEHOLDER = "{element_list}"
_BOX_FIELDS = ("x_min", "y_min", "x_max", "y_max")


class BoxSlotConfig(NamedTuple):
    """The full parameter set of the p07 box slot.

    box_config_hash covers all fields - a change to one of them moves
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


def box_config_hash(config: BoxSlotConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the config."""
    return sha256_hex(canonical_json(dict(config._asdict())))


def _box_value_schema() -> dict[str, JsonValue]:
    """The strict schema for one box object."""
    bound: dict[str, JsonValue] = {"type": "number", "minimum": 0, "maximum": 1}
    return {
        "type": "object",
        "properties": {field: dict(bound) for field in _BOX_FIELDS},
        "required": list(_BOX_FIELDS),
        "additionalProperties": False,
    }


def _boxes_schema(elements: Sequence[str]) -> dict[str, JsonValue]:
    """The strict schema for one image: one box or null for each element."""
    box_schema = _box_value_schema()
    return {
        "type": "object",
        "properties": {
            element: {"anyOf": [box_schema, {"type": "null"}]} for element in elements
        },
        "required": list(elements),
        "additionalProperties": False,
    }


def _checked_box(element: str, value: Mapping[str, object]) -> Box:
    """One validated Box. A range or shape violation raises."""
    if set(value) != set(_BOX_FIELDS):
        raise OpenRouterResponseError(
            f"element {element!r}: box key set is wrong: {sorted(value)}"
        )
    numbers: dict[str, float] = {}
    for field in _BOX_FIELDS:
        raw = value[field]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise OpenRouterResponseError(
                f"element {element!r}: {field} is not a number: {raw!r}"
            )
        number = float(raw)
        if not 0.0 <= number <= 1.0:
            raise OpenRouterResponseError(
                f"element {element!r}: {field} is out of [0, 1]: {number}"
            )
        numbers[field] = number
    if not numbers["x_min"] < numbers["x_max"] or not numbers["y_min"] < numbers["y_max"]:
        raise OpenRouterResponseError(
            f"element {element!r}: box is empty or inverted: {numbers}"
        )
    return Box(numbers["x_min"], numbers["y_min"], numbers["x_max"], numbers["y_max"])


def _parsed_boxes(
    payload: Mapping[str, object], elements: tuple[str, ...]
) -> dict[str, Box | None]:
    """The validated box mapping for one image. A violation raises."""
    if set(payload) != set(elements):
        missing = sorted(set(elements) - set(payload))
        extra = sorted(set(payload) - set(elements))
        raise OpenRouterResponseError(
            f"box payload key set does not equal the queried set "
            f"(missing {missing}, extra {extra})"
        )
    result: dict[str, Box | None] = {}
    for element in elements:
        value = payload[element]
        if value is None:
            result[element] = None
        elif isinstance(value, dict):
            result[element] = _checked_box(element, value)
        else:
            raise OpenRouterResponseError(
                f"element {element!r}: value is not a box object or null: {value!r}"
            )
    return result


class OpenRouterElementBoxDetector:
    """ElementBoxDetector through OpenRouter - the p07 slot.

    The instruction template must contain the {element_list}
    placeholder. The provider replaces it verbatim with the quoted
    element strings. An empty query gives an empty mapping with no
    POST and no cache entry.
    """

    def __init__(
        self,
        slot_config: BoxSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
    ) -> None:
        checked_response_format_mode(slot_config.response_format_mode)
        if _ELEMENT_PLACEHOLDER not in slot_config.template:
            raise ValueError(
                f"box instruction template must contain {_ELEMENT_PLACEHOLDER!r}"
            )
        self._slot_config = slot_config
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else default_clock
        self._config_hash = box_config_hash(slot_config)
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

    def detect_boxes(
        self,
        images: Sequence[bytes],
        element_lists: Sequence[Sequence[str]],
    ) -> list[dict[str, Box | None]]:
        """One box or None for each queried element of each image.

        element_lists is index-aligned with images. A query with
        duplicate element strings raises ValueError - the payload
        keys could not tell the duplicates apart.
        """
        if len(images) != len(element_lists):
            raise ValueError(
                "images and element_lists are not index-aligned: "
                f"{len(images)} images, {len(element_lists)} element lists"
            )
        results: list[dict[str, Box | None]] = []
        for image_bytes, raw_elements in zip(images, element_lists, strict=True):
            elements = tuple(raw_elements)
            if len(set(elements)) != len(elements):
                raise ValueError(
                    f"duplicate element strings in one query: {sorted(elements)}"
                )
            if not elements:
                results.append({})
                continue
            results.append(self._resolved_boxes(image_bytes, elements))
        return results

    def _resolved_boxes(
        self, image_bytes: bytes, elements: tuple[str, ...]
    ) -> dict[str, Box | None]:
        """Resolve one image through the cache, keyed by image and query.

        Each image resolves on its own because its parser and schema
        close on that image's element list (spec P1b section 6).
        """
        image_id = sha256_hex(image_bytes)
        element_list_hash = sha256_hex(canonical_json(list(elements)))
        key = sha256_hex(image_id + ":" + element_list_hash)
        # The classifier's quoting style: '"a", "b"'.
        quoted = '"' + '", "'.join(elements) + '"'
        instruction = self._slot_config.template.replace(_ELEMENT_PLACEHOLDER, quoted)
        schema = _boxes_schema(elements)

        def body_at(index: int) -> dict[str, JsonValue]:
            return chat_request_body(self._slot_config, instruction, image_bytes, schema)

        def parse(response_body: object) -> dict[str, Box | None]:
            return _parsed_boxes(json_payload(response_body), elements)

        def entry_extra_at(index: int) -> dict[str, JsonValue]:
            return {
                "image_id": image_id,
                "element_list_hash": element_list_hash,
                "elements": list(elements),
            }

        values, hits = resolve_chat(
            [key],
            [image_id],
            body_at,
            parse,
            self._config_hash,
            self._slot_config.model,
            self._client,
            self._cache_root,
            self._clock,
            entry_extra_at=entry_extra_at,
        )
        self._cache_hit_count += hits
        return values[0]
