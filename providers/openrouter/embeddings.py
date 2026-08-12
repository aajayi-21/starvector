"""OpenRouter embedding encoders - the TextEncoder and ImageEncoder slots.

Spec: docs/specs/pool-preparation.md section 8 (U2). The two encoders
POST to the /embeddings endpoint and cache one entry for each input
item. Output vectors are unit-norm float32 (R9). A response with an
incorrect row count, an incorrect dimension, a non-finite value, or a
zero-norm row raises (R14).
"""

import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import Vectors
from providers.openrouter.cache import load_cached_response, response_cache_path, store_response
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


def _validated_row(
    embedding: object, dimension: int, key: str, model: str
) -> list[float]:
    """One embedding row as finite floats of the configured dimension."""
    if not isinstance(embedding, list):
        raise OpenRouterResponseError(
            f"item {key} (model {model}): embedding is not an array: {embedding!r}"
        )
    if len(embedding) != dimension:
        raise OpenRouterResponseError(
            f"item {key} (model {model}): embedding has {len(embedding)} values, "
            f"the config pins {dimension}"
        )
    row: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise OpenRouterResponseError(
                f"item {key} (model {model}): embedding value is not a number: {value!r}"
            )
        number = float(value)
        if not math.isfinite(number):
            raise OpenRouterResponseError(
                f"item {key} (model {model}): embedding value is not finite: {number!r}"
            )
        row.append(number)
    return row


def _item_byte_size(item: JsonValue) -> int:
    """The byte count one input item adds to a POST body."""
    if isinstance(item, str):
        return len(item.encode("utf-8"))
    return len(canonical_json(item).encode("utf-8"))


def _batched_keys(
    keys: Sequence[str], sizes: dict[str, int], batch_size: int
) -> list[list[str]]:
    """Split keys into POST groups by count and by accumulated bytes."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_bytes = 0
    for key in keys:
        size = sizes[key]
        if current and (
            len(current) >= batch_size or current_bytes + size > _BATCH_BYTE_LIMIT
        ):
            batches.append(current)
            current = []
            current_bytes = 0
        current.append(key)
        current_bytes += size
    if current:
        batches.append(current)
    return batches


def _placed_rows(
    response_body: dict[str, object],
    group: Sequence[str],
    config: EmbeddingSlotConfig,
) -> list[list[float]]:
    """The validated rows of one embeddings response, placed by index.

    Each "data" row has an "index" field. The index values must be
    0 through k-1 with no repeats for a k-item group, and each row's
    embedding must be finite floats of the configured dimension.
    """
    prefix = f"embeddings response for item {group[0]} (model {config.model})"
    data = response_body.get("data")
    if not isinstance(data, list):
        raise OpenRouterResponseError(f'{prefix}: "data" is not an array')
    if len(data) != len(group):
        raise OpenRouterResponseError(
            f"{prefix}: {len(data)} rows came back for {len(group)} inputs"
        )
    placed: list[list[float] | None] = [None] * len(group)
    for row in data:
        if not isinstance(row, dict) or "index" not in row or "embedding" not in row:
            raise OpenRouterResponseError(
                f'{prefix}: a data row has no "index" or no "embedding"'
            )
        position = row["index"]
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or not 0 <= position < len(group)
            or placed[position] is not None
        ):
            raise OpenRouterResponseError(
                f'{prefix}: "index" values are not exactly 0 through {len(group) - 1}'
            )
        placed[position] = _validated_row(
            row["embedding"], config.dimension, group[position], config.model
        )
    return [row for row in placed if row is not None]


def _resolved_rows(
    keys: Sequence[str],
    item_at: Callable[[int], JsonValue],
    input_kind: str,
    config: EmbeddingSlotConfig,
    config_hash: str,
    client: OpenRouterClient,
    cache_root: Path,
    clock: Callable[[], str],
    batch_size: int,
    entry_extra: Mapping[str, JsonValue] | None = None,
) -> tuple[list[list[float]], int]:
    """Cache-first resolution of one embedding row for each input index.

    A cache hit is validated again (length and finiteness). Misses are
    deduplicated by key, batched by count and by accumulated bytes,
    sent through client.post_embeddings, validated, and then stored
    one entry for each item — with the entry_extra fields merged in
    when that mapping is not None. The first output is index-aligned
    with keys. The second output is the cache hit count across
    deduplicated keys.
    """
    rows_by_key: dict[str, list[float]] = {}
    items_by_key: dict[str, JsonValue] = {}
    sizes: dict[str, int] = {}
    miss_keys: list[str] = []
    cache_hits = 0
    for index, key in enumerate(keys):
        if key in rows_by_key or key in items_by_key:
            continue
        path = response_cache_path(cache_root, config_hash, key)
        entry = load_cached_response(path)
        if entry is not None:
            if "embedding" not in entry:
                raise OpenRouterResponseError(f"{path}: cache entry has no embedding")
            rows_by_key[key] = _validated_row(
                entry["embedding"], config.dimension, key, config.model
            )
            cache_hits += 1
            continue
        item = item_at(index)
        items_by_key[key] = item
        sizes[key] = _item_byte_size(item)
        miss_keys.append(key)
    def post_group(group: Sequence[str]) -> None:
        body: dict[str, JsonValue] = {
            "model": config.model,
            "input": [items_by_key[key] for key in group],
            "encoding_format": config.encoding_format,
        }
        try:
            response_body = client.post_embeddings(body)
        except OpenRouterTimeoutError:
            # A batch the endpoint cannot finish in the timeout
            # splits in half and goes again, down to one item. The
            # rows cannot change - each item embeds on its own and
            # lands by index - and the batch shape is not part of a
            # hash. A one-item timeout is an unrepairable failure
            # and raises.
            if len(group) <= 1:
                raise
            middle = len(group) // 2
            post_group(group[:middle])
            post_group(group[middle:])
            return
        rows = _placed_rows(response_body, group, config)
        for key, row in zip(group, rows, strict=True):
            entry = {
                "key": key,
                "config_hash": config_hash,
                "model": config.model,
                "input_kind": input_kind,
                "embedding": row,
                "created_at": clock(),
            }
            if entry_extra is not None:
                entry.update(entry_extra)
            store_response(response_cache_path(cache_root, config_hash, key), entry)
            rows_by_key[key] = row

    for group in _batched_keys(miss_keys, sizes, batch_size):
        post_group(group)
    return [rows_by_key[key] for key in keys], cache_hits


def _unit_norm_vectors(
    rows: Sequence[Sequence[float]],
    keys: Sequence[str],
    dimension: int,
    model: str,
) -> Vectors:
    """Stack rows to (B, d) float64, check, unit-normalize, cast float32.

    A non-finite value or a zero-norm row raises - a normalized zero
    row is a silent fallback (R14).
    """
    if not rows:
        return np.zeros((0, dimension), dtype=np.float32)
    stacked = np.asarray(rows, dtype=np.float64)  # (B, d)
    bad_rows = np.where(~np.isfinite(stacked).all(axis=1))[0]
    if bad_rows.size:
        raise OpenRouterResponseError(
            f"item {keys[int(bad_rows[0])]} (model {model}): "
            "embedding row is not finite"
        )
    norms = np.linalg.norm(stacked, axis=1)  # (B,)
    zero_rows = np.where(norms == 0.0)[0]
    if zero_rows.size:
        raise OpenRouterResponseError(
            f"item {keys[int(zero_rows[0])]} (model {model}): "
            "embedding row has zero norm and cannot be unit-normalized"
        )
    unit = stacked / norms[:, np.newaxis]  # (B, d)
    return unit.astype(np.float32)


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

        rows, hits = _resolved_rows(
            keys,
            item_at,
            "text",
            self._slot_config,
            self._config_hash,
            self._client,
            self._cache_root,
            self._clock,
            self._batch_size,
        )
        self._cache_hit_count += hits
        return _unit_norm_vectors(
            rows, keys, self._slot_config.dimension, self._slot_config.model
        )


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

        rows, hits = _resolved_rows(
            keys,
            item_at,
            "image",
            self._slot_config,
            self._config_hash,
            self._client,
            self._cache_root,
            self._clock,
            self._batch_size,
            entry_extra=(
                None if instruction is None else {"instruction": instruction}
            ),
        )
        self._cache_hit_count += hits
        return _unit_norm_vectors(
            rows, keys, self._slot_config.dimension, self._slot_config.model
        )
