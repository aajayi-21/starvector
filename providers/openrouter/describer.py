"""OpenRouter VlmDescriber - the p01 element extraction slot.

Spec: docs/specs/pool-preparation.md section 8 and decision D2. One
POST for each image, temperature 0, a fixed instruction template with
no placeholder, and a strict JSON output format that pins the count of
each array field. The parsed response becomes one ElementResponse for
each image (R2). A response that does not parse, an incorrect key set,
a count violation, an empty entry, or a non-string entry raises (R14).
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
from providers.protocols import ElementResponse

DESCRIBER_MAX_TOKENS = 512

# The R2 field sequence. The fields with pinned counts are arrays.
# The fifth and sixth R2 fields are plain strings (protocols.ElementResponse).
_ARRAY_FIELDS = ("objects", "materials", "colors", "shapes", "ambience")
_STRING_FIELDS = ("scale", "setting")
_ALL_FIELDS = ("objects", "materials", "colors", "shapes", "scale", "setting", "ambience")


class DescriberSlotConfig(NamedTuple):
    """The full parameter set of the p01 describer slot.

    describer_config_hash covers all fields - a template change or a
    count change moves the cache tree (R12). The API key is not a
    field here and is not part of the hash.
    """

    slot: str
    model: str
    template: str
    temperature: float
    seed: int
    max_tokens: int
    reasoning_enabled: bool
    response_format_mode: str
    objects_count: int
    materials_count: int
    colors_count: int
    shapes_count: int
    ambience_count: int


def describer_config_hash(config: DescriberSlotConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the config."""
    return sha256_hex(canonical_json(dict(config._asdict())))


def _count_for(config: DescriberSlotConfig, field: str) -> int:
    counts = {
        "objects": config.objects_count,
        "materials": config.materials_count,
        "colors": config.colors_count,
        "shapes": config.shapes_count,
        "ambience": config.ambience_count,
    }
    return counts[field]


def _element_schema(config: DescriberSlotConfig) -> dict[str, JsonValue]:
    """The strict R2 schema, with minItems == maxItems for each array."""
    properties: dict[str, JsonValue] = {}
    for field in _ALL_FIELDS:
        if field in _STRING_FIELDS:
            properties[field] = {"type": "string"}
        else:
            count = _count_for(config, field)
            properties[field] = {
                "type": "array",
                "items": {"type": "string"},
                "minItems": count,
                "maxItems": count,
            }
    return {
        "type": "object",
        "properties": properties,
        "required": list(_ALL_FIELDS),
        "additionalProperties": False,
    }


def _checked_entry(field: str, value: object) -> str:
    """One non-empty string entry. A different value raises."""
    if not isinstance(value, str):
        raise OpenRouterResponseError(f"{field} entry is not a string: {value!r}")
    if not value.strip():
        raise OpenRouterResponseError(f"{field} entry is empty or whitespace-only")
    return value


def _parsed_element_response(
    payload: Mapping[str, object], config: DescriberSlotConfig
) -> ElementResponse:
    """The validated ElementResponse for one payload. A violation raises."""
    if set(payload) != set(_ALL_FIELDS):
        missing = sorted(set(_ALL_FIELDS) - set(payload))
        extra = sorted(set(payload) - set(_ALL_FIELDS))
        raise OpenRouterResponseError(
            f"element response key set is wrong (missing {missing}, extra {extra})"
        )
    arrays: dict[str, tuple[str, ...]] = {}
    for field in _ARRAY_FIELDS:
        value = payload[field]
        if not isinstance(value, list):
            raise OpenRouterResponseError(f"{field} is not an array: {value!r}")
        expected = _count_for(config, field)
        if len(value) != expected:
            raise OpenRouterResponseError(
                f"{field} has {len(value)} entries, the contract pins {expected}"
            )
        arrays[field] = tuple(_checked_entry(field, entry) for entry in value)
    strings: dict[str, str] = {}
    for field in _STRING_FIELDS:
        value = payload[field]
        if isinstance(value, list):
            raise OpenRouterResponseError(
                f"{field} is an array, the contract pins a plain string"
            )
        strings[field] = _checked_entry(field, value)
    return ElementResponse(
        objects=arrays["objects"],
        materials=arrays["materials"],
        colors=arrays["colors"],
        shapes=arrays["shapes"],
        scale=strings["scale"],
        setting=strings["setting"],
        ambience=arrays["ambience"],
    )


class OpenRouterVlmDescriber:
    """VlmDescriber through OpenRouter - the p01 slot.

    The instruction template is fixed text with no placeholder. The
    array-field counts sit in the config, thus a count change moves
    the config hash and the cache tree.
    """

    def __init__(
        self,
        slot_config: DescriberSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
    ) -> None:
        checked_response_format_mode(slot_config.response_format_mode)
        self._slot_config = slot_config
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else default_clock
        self._config_hash = describer_config_hash(slot_config)
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

    def describe_images(self, images: Sequence[bytes]) -> list[ElementResponse]:
        """One parsed ElementResponse for each image, index-aligned."""
        schema = _element_schema(self._slot_config)
        keys = [sha256_hex(image) for image in images]

        def body_at(index: int) -> dict[str, JsonValue]:
            return chat_request_body(
                self._slot_config, self._slot_config.template, images[index], schema
            )

        def parse(response_body: object) -> ElementResponse:
            return _parsed_element_response(json_payload(response_body), self._slot_config)

        values, hits = resolve_chat(
            keys,
            keys,
            body_at,
            parse,
            self._config_hash,
            self._slot_config.model,
            self._client,
            self._cache_root,
            self._clock,
        )
        self._cache_hit_count += hits
        return values
