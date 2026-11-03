"""Cache-first embedding rows for each provider that posts to an API.

Spec: docs/specs/pool-preparation.md section 8 (U2) and
docs/specs/voyage-encoder.md section 3. The rules here are the same for
each provider: one cache entry for each input item, misses deduplicated
and batched, a timed-out batch split in half, and unit-norm float32
output (R9). A response with an incorrect row count, an incorrect
dimension, a non-finite value, or a zero-norm row raises (R14). A
provider supplies its HTTP body, its error types, and its row encoding.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import numpy as np

from core.canonical import JsonValue, canonical_json
from core.types import Vectors
from providers.response_cache import (load_cached_response,
                                      response_cache_path, store_response)

# One row: JSON floats or decoded float32 values. Each of the two stacks
# through numpy without a provider branch.
Row = list[float] | np.ndarray


class RowRules(NamedTuple):
    """The provider-side facts the shared row rules read."""

    model: str
    dimension: int
    response_error: type[Exception]
    timeout_error: type[Exception]
    byte_limit: int
    token_limit: int | None = None


class RowCodec(NamedTuple):
    """How one row is written to, and read from, a cache entry."""

    read: Callable[[Mapping[str, JsonValue], str, Path], Row]
    fields: Callable[[Row], dict[str, JsonValue]]


def validated_row(embedding: object, key: str, rules: RowRules) -> list[float]:
    """One embedding row as finite floats of the configured dimension."""
    if not isinstance(embedding, list):
        raise rules.response_error(
            f"item {key} (model {rules.model}): embedding is not an array: {embedding!r}"
        )
    if len(embedding) != rules.dimension:
        raise rules.response_error(
            f"item {key} (model {rules.model}): embedding has {len(embedding)} values, "
            f"the config pins {rules.dimension}"
        )
    row: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise rules.response_error(
                f"item {key} (model {rules.model}): embedding value is not a number: {value!r}"
            )
        number = float(value)
        if not math.isfinite(number):
            raise rules.response_error(
                f"item {key} (model {rules.model}): embedding value is not finite: {number!r}"
            )
        row.append(number)
    return row


def float_list_codec(rules: RowRules) -> RowCodec:
    """Rows stored as JSON floats, in the "embedding" field."""

    def read(entry: Mapping[str, JsonValue], key: str, path: Path) -> Row:
        if "embedding" not in entry:
            raise rules.response_error(f"{path}: cache entry has no embedding")
        return validated_row(entry["embedding"], key, rules)

    def fields(row: Row) -> dict[str, JsonValue]:
        return {"embedding": row}  # type: ignore[dict-item]

    return RowCodec(read=read, fields=fields)


def item_byte_size(item: JsonValue) -> int:
    """The byte count one input item adds to a POST body."""
    if isinstance(item, str):
        return len(item.encode("utf-8"))
    return len(canonical_json(item).encode("utf-8"))


def batched_keys(
    keys: Sequence[str],
    sizes: Mapping[str, int],
    batch_size: int,
    rules: RowRules,
    tokens: Mapping[str, int] | None = None,
) -> list[list[str]]:
    """Split keys into POST groups by count, bytes, and estimated tokens."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_bytes = 0
    current_tokens = 0
    for key in keys:
        size = sizes[key]
        token_count = tokens[key] if tokens is not None else 0
        over_tokens = (rules.token_limit is not None
                       and current_tokens + token_count > rules.token_limit)
        if current and (
            len(current) >= batch_size
            or current_bytes + size > rules.byte_limit
            or over_tokens
        ):
            batches.append(current)
            current = []
            current_bytes = 0
            current_tokens = 0
        current.append(key)
        current_bytes += size
        current_tokens += token_count
    if current:
        batches.append(current)
    return batches


def placed_rows(
    response_body: Mapping[str, object],
    group: Sequence[str],
    rules: RowRules,
    row_of: Callable[[object, str], Row],
) -> list[Row]:
    """The validated rows of one embeddings response, placed by index.

    Each "data" row has an "index" field. The index values must be
    0 through k-1 with no repeats for a k-item group, and each row goes
    through row_of with the key of its position.
    """
    prefix = f"embeddings response for item {group[0]} (model {rules.model})"
    data = response_body.get("data")
    if not isinstance(data, list):
        raise rules.response_error(f'{prefix}: "data" is not an array')
    if len(data) != len(group):
        raise rules.response_error(
            f"{prefix}: {len(data)} rows came back for {len(group)} inputs"
        )
    placed: list[Row | None] = [None] * len(group)
    for row in data:
        if not isinstance(row, dict) or "index" not in row or "embedding" not in row:
            raise rules.response_error(
                f'{prefix}: a data row has no "index" or no "embedding"'
            )
        position = row["index"]
        if (
            isinstance(position, bool)
            or not isinstance(position, int)
            or not 0 <= position < len(group)
            or placed[position] is not None
        ):
            raise rules.response_error(
                f'{prefix}: "index" values are not exactly 0 through {len(group) - 1}'
            )
        placed[position] = row_of(row["embedding"], group[position])
    return [row for row in placed if row is not None]


def resolved_rows(
    keys: Sequence[str],
    item_at: Callable[[int], JsonValue],
    input_kind: str,
    config_hash: str,
    rules: RowRules,
    codec: RowCodec,
    post_items: Callable[[Sequence[str], Sequence[JsonValue]], Sequence[Row]],
    cache_root: Path,
    clock: Callable[[], str],
    batch_size: int,
    entry_extra: Mapping[str, JsonValue] | None = None,
    tokens_at: Callable[[int], int] | None = None,
) -> tuple[list[Row], int]:
    """Cache-first resolution of one embedding row for each input index.

    A cache hit is validated again by the codec. Misses are deduplicated
    by key, batched, sent through post_items, and then stored one entry
    for each item - with the entry_extra fields merged in when that
    mapping is not None. The first output is index-aligned with keys.
    The second output is the cache hit count across deduplicated keys.
    """
    rows_by_key: dict[str, Row] = {}
    items_by_key: dict[str, JsonValue] = {}
    sizes: dict[str, int] = {}
    tokens: dict[str, int] = {}
    miss_keys: list[str] = []
    cache_hits = 0
    for index, key in enumerate(keys):
        if key in rows_by_key or key in items_by_key:
            continue
        path = response_cache_path(cache_root, config_hash, key)
        entry = load_cached_response(path, rules.response_error)
        if entry is not None:
            rows_by_key[key] = codec.read(entry, key, path)
            cache_hits += 1
            continue
        item = item_at(index)
        items_by_key[key] = item
        sizes[key] = item_byte_size(item)
        if tokens_at is not None:
            tokens[key] = tokens_at(index)
        miss_keys.append(key)

    def post_group(group: Sequence[str]) -> None:
        try:
            rows = post_items(group, [items_by_key[key] for key in group])
        except rules.timeout_error:
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
        for key, row in zip(group, rows, strict=True):
            entry: dict[str, JsonValue] = {
                "key": key,
                "config_hash": config_hash,
                "model": rules.model,
                "input_kind": input_kind,
                "created_at": clock(),
            }
            entry.update(codec.fields(row))
            if entry_extra is not None:
                entry.update(entry_extra)
            store_response(response_cache_path(cache_root, config_hash, key), entry)
            rows_by_key[key] = row

    token_map = tokens if tokens_at is not None else None
    for group in batched_keys(miss_keys, sizes, batch_size, rules, token_map):
        post_group(group)
    return [rows_by_key[key] for key in keys], cache_hits


def unit_norm_vectors(
    rows: Sequence[Row], keys: Sequence[str], rules: RowRules
) -> Vectors:
    """Stack rows to (B, d) float64, check, unit-normalize, cast float32.

    A non-finite value or a zero-norm row raises - a normalized zero
    row is a silent fallback (R14).
    """
    if not rows:
        return np.zeros((0, rules.dimension), dtype=np.float32)
    stacked = np.asarray(rows, dtype=np.float64)  # (B, d)
    bad_rows = np.where(~np.isfinite(stacked).all(axis=1))[0]
    if bad_rows.size:
        raise rules.response_error(
            f"item {keys[int(bad_rows[0])]} (model {rules.model}): "
            "embedding row is not finite"
        )
    norms = np.linalg.norm(stacked, axis=1)  # (B,)
    zero_rows = np.where(norms == 0.0)[0]
    if zero_rows.size:
        raise rules.response_error(
            f"item {keys[int(zero_rows[0])]} (model {rules.model}): "
            "embedding row has zero norm and cannot be unit-normalized"
        )
    unit = stacked / norms[:, np.newaxis]  # (B, d)
    return unit.astype(np.float32)
