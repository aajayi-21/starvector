"""OpenRouter embedding encoders - the TextEncoder and ImageEncoder slots.

Spec: docs/specs/pool-preparation.md section 8 (U2). The two encoders
POST to the /embeddings endpoint and cache one entry for each input
item. Output vectors are unit-norm float32 (R9). A response with an
incorrect row count, an incorrect dimension, a non-finite value, or a
zero-norm row raises (R14).
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NamedTuple

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import Vectors
from providers.embedding_rows import (Row, RowRules, float_list_codec,
                                      placed_rows, resolved_rows,
                                      unit_norm_vectors, validated_row)
from providers.openrouter.client import OpenRouterClient
from providers.openrouter.errors import (OpenRouterResponseError,
                                         OpenRouterTimeoutError)
from providers.openrouter.resolve import data_uri, default_clock

EMBEDDING_BATCH_SIZE = 64

# One embeddings POST body stays below this byte count, measured on the
# accumulated input items. Data URIs for images are large, thus a count
# limit alone is not sufficient.
_BATCH_BYTE_LIMIT = 8_000_000


class EmbeddingSlotConfig(NamedTuple):
    """The full parameter set of one embeddings slot.

    embedding_config_hash covers all fields, the slot name included,
    thus the text slot and the image slot keep their own cache trees
    also when the model is the same (CLAUDE.md section 6).

    instruction is the joint-embedding text of spec P2c section 5.
    The image encoder sends it with each image in one item. None means
    the plain image item, and the hash document omits the field at
    None, thus each hash released before the field stays unchanged
    (P2c R5). The text slot does not implement instructions (P2c R7).
    """

    slot: str
    model: str
    dimension: int
    encoding_format: str
    instruction: str | None = None


def embedding_config_hash(config: EmbeddingSlotConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the config.

    The instruction field is omitted at None (P2c R5), thus a config
    without one hashes as it did before the field existed.
    """
    document = dict(config._asdict())
    if document["instruction"] is None:
        del document["instruction"]
    return sha256_hex(canonical_json(document))


def _row_rules(config: EmbeddingSlotConfig) -> RowRules:
    """The shared row rules with the OpenRouter errors bound."""
    return RowRules(
        model=config.model,
        dimension=config.dimension,
        response_error=OpenRouterResponseError,
        timeout_error=OpenRouterTimeoutError,
        byte_limit=_BATCH_BYTE_LIMIT,
    )


def _post_items(
    config: EmbeddingSlotConfig, client: OpenRouterClient
) -> Callable[[Sequence[str], Sequence[JsonValue]], Sequence[Row]]:
    """The POST step of the shared rows: one body, rows placed by index."""
    rules = _row_rules(config)

    def row_of(embedding: object, key: str) -> Row:
        return validated_row(embedding, key, rules)

    def post(group: Sequence[str], items: Sequence[JsonValue]) -> Sequence[Row]:
        body: dict[str, JsonValue] = {
            "model": config.model,
            "input": list(items),
            "encoding_format": config.encoding_format,
        }
        return placed_rows(client.post_embeddings(body), group, rules, row_of)

    return post


class OpenRouterTextEncoder:
    """TextEncoder through OpenRouter - the p04 slot.

    The slot does not implement instructions: a slot config with one
    raises here, at construction, and is not silently ignored (P2c
    R7).
    """

    def __init__(
        self,
        slot_config: EmbeddingSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        if slot_config.instruction is not None:
            raise ValueError(
                f"slot {slot_config.slot}: the text encoder does not "
                "implement instructions (P2c R7)"
            )
        self._slot_config = slot_config
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else default_clock
        self._batch_size = batch_size
        self._config_hash = embedding_config_hash(slot_config)
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

    def encode_texts(self, texts: Sequence[str]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm."""
        keys = [sha256_hex("text:" + text) for text in texts]

        def item_at(index: int) -> JsonValue:
            return texts[index]

        rules = _row_rules(self._slot_config)
        rows, hits = resolved_rows(
            keys,
            item_at,
            "text",
            self._config_hash,
            rules,
            float_list_codec(rules),
            _post_items(self._slot_config, self._client),
            self._cache_root,
            self._clock,
            self._batch_size,
        )
        self._cache_hit_count += hits
        return unit_norm_vectors(rows, keys, rules)


class OpenRouterImageEncoder:
    """ImageEncoder through OpenRouter - the p06 slot.

    Image input goes through content blocks with a data URI, the shape
    the embeddings endpoint accepts (U2). With an instruction in the
    slot config, each item holds two content entries — the instruction
    text first, the image second, the entry sequence the chat slots
    use — and one joint embedding row comes back (spec P2c section 5).
    """

    def __init__(
        self,
        slot_config: EmbeddingSlotConfig,
        client: OpenRouterClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self._slot_config = slot_config
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else default_clock
        self._batch_size = batch_size
        self._config_hash = embedding_config_hash(slot_config)
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

    def encode_images(self, images: Sequence[bytes]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm."""
        keys = [sha256_hex(image) for image in images]
        instruction = self._slot_config.instruction

        def item_at(index: int) -> JsonValue:
            # One input item is a content wrapper around the image
            # entry, not the bare entry - checked live 2026-08-08: the
            # bare shape fails the endpoint's input union, the wrapped
            # shape returns rows at dimension 3072.
            image_entry: JsonValue = {
                "type": "image_url",
                "image_url": {"url": data_uri(images[index])},
            }
            if instruction is None:
                return {"content": [image_entry]}
            return {
                "content": [
                    {"type": "text", "text": instruction},
                    image_entry,
                ]
            }

        rules = _row_rules(self._slot_config)
        rows, hits = resolved_rows(
            keys,
            item_at,
            "image",
            self._config_hash,
            rules,
            float_list_codec(rules),
            _post_items(self._slot_config, self._client),
            self._cache_root,
            self._clock,
            self._batch_size,
            entry_extra=(
                None if instruction is None else {"instruction": instruction}
            ),
        )
        self._cache_hit_count += hits
        return unit_norm_vectors(rows, keys, rules)
