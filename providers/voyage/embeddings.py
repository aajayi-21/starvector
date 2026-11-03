"""Voyage embedding encoders - the image, sketch, and text encoder slots.

Spec: docs/specs/voyage-encoder.md section 3. Each encoder posts to the
multimodal endpoint and caches one entry for each input item. Output
vectors are unit-norm float32 (R9), from the row rules each embedding
provider shares. The POST fields below are fixed and enter the hash.
"""

import base64
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import Vectors
from providers.embedding_rows import (Row, RowCodec, RowRules, placed_rows,
                                      resolved_rows, unit_norm_vectors)
from providers.voyage.client import VoyageClient, VoyageUsage
from providers.voyage.errors import VoyageResponseError, VoyageTimeoutError

EMBEDDING_BATCH_SIZE = 64

# The endpoint refuses one POST above this estimate of tokens.
_POST_TOKEN_LIMIT = 320_000
_BATCH_BYTE_LIMIT = 8_000_000
_PIXELS_FOR_EACH_TOKEN = 560
# A high estimate for English. The estimate paces POSTs and limits a
# batch, and the endpoint's own count decides the credit use.
_CHARACTERS_FOR_EACH_TOKEN = 3

# The default value can drop a full image from an input with no error,
# which is a silent fallback (spec VE1 section 3).
_TRUNCATION = False
# The instruction text is the item in the test, thus no fixed prompt.
_INPUT_TYPE = None
_OUTPUT_ENCODING = "base64"


class VoyageSlotConfig(NamedTuple):
    """The full parameter set of one Voyage embeddings slot.

    voyage_config_hash covers all fields, the slot name included, thus
    each slot keeps its own cache tree also when the model is the same
    (CLAUDE.md section 6). The instruction goes with each image in one
    item. None means the plain image item.
    """

    slot: str
    model: str
    dimension: int
    instruction: str | None = None


def voyage_config_hash(config: VoyageSlotConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the slot.

    The document names the provider and the fixed POST fields, thus
    a vector of this provider cannot share a cache tree with a vector
    of a different provider.
    """
    document: dict[str, JsonValue] = {
        "provider": "voyage",
        "slot": config.slot,
        "model": config.model,
        "dimension": config.dimension,
        "truncation": _TRUNCATION,
        "input_type": _INPUT_TYPE,
        "output_encoding": _OUTPUT_ENCODING,
    }
    if config.instruction is not None:
        document["instruction"] = config.instruction
    return sha256_hex(canonical_json(document))


def _row_rules(config: VoyageSlotConfig, tokens_per_minute: int) -> RowRules:
    return RowRules(
        model=config.model,
        dimension=config.dimension,
        response_error=VoyageResponseError,
        timeout_error=VoyageTimeoutError,
        byte_limit=_BATCH_BYTE_LIMIT,
        token_limit=min(_POST_TOKEN_LIMIT, tokens_per_minute),
    )


def _decoded_row(encoded: object, key: str, rules: RowRules) -> np.ndarray:
    """One base64 row as finite float32 values, shape (d,)."""
    if not isinstance(encoded, str):
        raise VoyageResponseError(
            f"item {key} (model {rules.model}): embedding is not base64 text"
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise VoyageResponseError(
            f"item {key} (model {rules.model}): embedding is not base64: {error}"
        ) from error
    if len(raw) != rules.dimension * 4:
        raise VoyageResponseError(
            f"item {key} (model {rules.model}): embedding has {len(raw) // 4} "
            f"values, the config pins {rules.dimension}"
        )
    row = np.frombuffer(raw, dtype="<f4")  # (d,)
    if not np.isfinite(row).all():
        raise VoyageResponseError(
            f"item {key} (model {rules.model}): embedding value is not finite"
        )
    return row


def _base64_codec(rules: RowRules) -> RowCodec:
    """Rows stored as base64 float32, about one tenth of the JSON floats."""

    def read(entry: Mapping[str, JsonValue], key: str, path: Path) -> Row:
        if "embedding_base64" not in entry:
            raise VoyageResponseError(f"{path}: cache entry has no embedding_base64")
        return _decoded_row(entry["embedding_base64"], key, rules)

    def fields(row: Row) -> dict[str, JsonValue]:
        raw = np.asarray(row, dtype="<f4").tobytes()
        return {"embedding_base64": base64.b64encode(raw).decode("ascii")}

    return RowCodec(read=read, fields=fields)


def _post_items(
    config: VoyageSlotConfig, client: VoyageClient, rules: RowRules,
    tokens_by_key: Mapping[str, int],
) -> Callable[[Sequence[str], Sequence[JsonValue]], Sequence[Row]]:
    """The POST step of the shared rows: one body, rows placed by index."""

    def row_of(encoded: object, key: str) -> Row:
        return _decoded_row(encoded, key, rules)

    def post(group: Sequence[str], items: Sequence[JsonValue]) -> Sequence[Row]:
        body: dict[str, JsonValue] = {
            "model": config.model,
            "inputs": list(items),
            "input_type": _INPUT_TYPE,
            "truncation": _TRUNCATION,
            "output_encoding": _OUTPUT_ENCODING,
        }
        estimate = sum(tokens_by_key[key] for key in group)
        response = client.post_embeddings(body, estimate)
        return placed_rows(response, group, rules, row_of)

    return post


def _text_tokens(text: str) -> int:
    return len(text) // _CHARACTERS_FOR_EACH_TOKEN + 1


def _image_tokens(image: bytes) -> int:
    """The token count the endpoint gives one image: pixels / 560."""
    with Image.open(BytesIO(image)) as opened:  # reads the header alone
        width, height = opened.size
    return width * height // _PIXELS_FOR_EACH_TOKEN + 1


def _image_data_uri(image: bytes) -> str:
    """The base64 data URI, with the media type read from magic bytes."""
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif image.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        media_type = "image/webp"
    elif image[:6] in (b"GIF87a", b"GIF89a"):
        media_type = "image/gif"
    else:
        raise ValueError(f"image media type is not one the endpoint reads: {image[:12]!r}")
    return f"data:{media_type};base64,{base64.b64encode(image).decode('ascii')}"


def _default_clock() -> str:
    """The UTC time in ISO 8601 text - the created_at value for new entries."""
    return datetime.now(timezone.utc).isoformat()


class _VoyageEncoder:
    """The cache-first encode that the image and text slots share."""

    def __init__(
        self,
        slot_config: VoyageSlotConfig,
        client: VoyageClient,
        cache_root: Path,
        clock: Callable[[], str] | None = None,
        batch_size: int = EMBEDDING_BATCH_SIZE,
    ) -> None:
        self._slot_config = slot_config
        self._client = client
        self._cache_root = Path(cache_root)
        self._clock = clock if clock is not None else _default_clock
        self._batch_size = batch_size
        self._config_hash = voyage_config_hash(slot_config)
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

    @property
    def usage(self) -> VoyageUsage:
        return self._client.usage

    def _encode(
        self,
        keys: Sequence[str],
        item_at: Callable[[int], JsonValue],
        tokens_at: Callable[[int], int],
        input_kind: str,
        entry_extra: Mapping[str, JsonValue] | None = None,
    ) -> Vectors:
        rules = _row_rules(self._slot_config, self._client.tokens_per_minute)
        tokens_by_key: dict[str, int] = {}

        def recorded_tokens(index: int) -> int:
            tokens_by_key[keys[index]] = tokens_at(index)
            return tokens_by_key[keys[index]]

        rows, hits = resolved_rows(
            keys,
            item_at,
            input_kind,
            self._config_hash,
            rules,
            _base64_codec(rules),
            _post_items(self._slot_config, self._client, rules, tokens_by_key),
            self._cache_root,
            self._clock,
            self._batch_size,
            entry_extra=entry_extra,
            tokens_at=recorded_tokens,
        )
        self._cache_hit_count += hits
        return unit_norm_vectors(rows, keys, rules)


class VoyageTextEncoder(_VoyageEncoder):
    """TextEncoder through Voyage.

    The slot does not implement instructions: a slot config with one
    raises here, at construction, and is not silently ignored (P2c R7).
    """

    def __init__(self, slot_config: VoyageSlotConfig, client: VoyageClient,
                 cache_root: Path, clock: Callable[[], str] | None = None,
                 batch_size: int = EMBEDDING_BATCH_SIZE) -> None:
        if slot_config.instruction is not None:
            raise ValueError(
                f"slot {slot_config.slot}: the text encoder does not "
                "implement instructions (P2c R7)"
            )
        super().__init__(slot_config, client, cache_root, clock, batch_size)

    def encode_texts(self, texts: Sequence[str]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm."""
        keys = [sha256_hex("text:" + text) for text in texts]

        def item_at(index: int) -> JsonValue:
            return {"content": [{"type": "text", "text": texts[index]}]}

        def tokens_at(index: int) -> int:
            return _text_tokens(texts[index])

        return self._encode(keys, item_at, tokens_at, "text")


class VoyageImageEncoder(_VoyageEncoder):
    """ImageEncoder and SketchEncoder through Voyage.

    With an instruction in the slot config, each item holds two content
    entries - the instruction text first, the image second, the entry
    sequence the OpenRouter slot uses - and one joint row comes back.
    """

    def encode_images(self, images: Sequence[bytes]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm."""
        keys = [sha256_hex(image) for image in images]
        instruction = self._slot_config.instruction

        def item_at(index: int) -> JsonValue:
            image_entry: JsonValue = {
                "type": "image_base64",
                "image_base64": _image_data_uri(images[index]),
            }
            if instruction is None:
                return {"content": [image_entry]}
            return {"content": [{"type": "text", "text": instruction},
                                image_entry]}

        def tokens_at(index: int) -> int:
            text = 0 if instruction is None else _text_tokens(instruction)
            return _image_tokens(images[index]) + text

        return self._encode(
            keys, item_at, tokens_at, "image",
            entry_extra=(None if instruction is None
                         else {"instruction": instruction}),
        )
