"""OpenRouter generalizer: one broader phrase for each element string.

Fills the Generalizer slot of docs/specs/fuse-and-validate.md section
8.2. The generalization-table build task asks this slot one question
for each pool vocabulary entry, one time, and caches each answer by
the entry string. The generator then reads the stored table and sends
nothing to the model itself.
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

from core.canonical import JsonValue, canonical_json, sha256_hex
from providers.openrouter.client import OpenRouterClient
from providers.openrouter.errors import OpenRouterResponseError
from providers.openrouter.resolve import (checked_response_format_mode,
                                          default_clock, json_payload,
                                          resolve_chat, text_request_body)

GENERALIZE_MAX_TOKENS = 128

# The instruction template must hold this placeholder — it is where
# the element string goes.
_ELEMENT_PLACEHOLDER = "{element}"


class GeneralizeSlotConfig(NamedTuple):
    """Frozen parameters for the generalization slot."""

    slot: str
    model: str
    template: str
    temperature: float
    seed: int
    max_tokens: int
    reasoning_enabled: bool
    response_format_mode: str


def generalize_config_hash(config: GeneralizeSlotConfig) -> str:
    """Stable hash across the slot parameters."""
    return sha256_hex(canonical_json(dict(config._asdict())))


def _phrase_schema() -> dict[str, JsonValue]:
    """The strict response shape: one broader phrase."""
    return {
        "type": "object",
        "properties": {"phrase": {"type": "string"}},
        "required": ["phrase"],
        "additionalProperties": False,
    }


def _parsed_phrase(payload: object) -> str:
    """One phrase from the response payload, validated."""
    if not isinstance(payload, dict) or set(payload) != {"phrase"}:
        raise OpenRouterResponseError(
            f"generalize payload must be an object with one phrase key, "
            f"got {payload!r}")
    phrase = payload["phrase"]
    if not isinstance(phrase, str) or not phrase.strip():
        raise OpenRouterResponseError(
            f"generalize phrase must be a non-empty string, got {phrase!r}")
    return phrase.strip()


class OpenRouterGeneralizer:
    """Generalizer through the OpenRouter chat endpoint.

    Batching is part of the contract: generalize takes the element
    strings and answers index-aligned. Caching, retries, and rate
    limits stay in this provider.
    """

    def __init__(self, slot_config: GeneralizeSlotConfig,
                 client: OpenRouterClient, cache_root: Path,
                 clock: Callable[[], str] | None = None) -> None:
        checked_response_format_mode(slot_config.response_format_mode)
        if _ELEMENT_PLACEHOLDER not in slot_config.template:
            raise ValueError(
                f"the instruction template must hold {_ELEMENT_PLACEHOLDER}")
        self._config = slot_config
        self._client = client
        self._cache_root = cache_root
        self._clock = clock or default_clock
        self._cache_hit_count = 0

    @property
    def config_hash(self) -> str:
        return generalize_config_hash(self._config)

    @property
    def cache_hit_count(self) -> int:
        return self._cache_hit_count

    @property
    def post_count(self) -> int:
        return self._client.post_count

    def generalize(self, texts: Sequence[str]) -> list[str]:
        """One broader phrase for each element string, index-aligned."""
        seen: set[str] = set()
        for text in texts:
            if not text or text in seen:
                raise ValueError(
                    f"element strings must be non-empty with no repeat: "
                    f"{text!r}")
            seen.add(text)
        keys = [sha256_hex("generalize:" + text) for text in texts]
        schema = _phrase_schema()

        def body_at(position: int) -> dict[str, JsonValue]:
            instruction = self._config.template.replace(
                _ELEMENT_PLACEHOLDER, texts[position])
            return text_request_body(self._config, instruction, schema)

        def parse(response_body: object) -> str:
            # json_payload reads the full response body itself — it
            # does the fence removal and the content extraction.
            return _parsed_phrase(json_payload(response_body))

        def entry_extra_at(position: int) -> dict[str, JsonValue]:
            return {"element": texts[position]}

        values, hits = resolve_chat(
            keys, list(texts), body_at, parse, self.config_hash,
            self._config.model, self._client, self._cache_root, self._clock,
            entry_extra_at=entry_extra_at)
        self._cache_hit_count += hits
        return values
