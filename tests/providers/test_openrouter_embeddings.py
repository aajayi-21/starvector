"""Offline tests for the OpenRouter embedding encoders, with httpx.MockTransport."""

import base64
import hashlib
import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from core.canonical import sha256_hex
from providers.openrouter.cache import load_cached_response, response_cache_path
from providers.openrouter.client import OpenRouterClient, OpenRouterClientConfig
from providers.openrouter.embeddings import (
    EMBEDDING_BATCH_SIZE,
    EmbeddingSlotConfig,
    OpenRouterImageEncoder,
    OpenRouterTextEncoder,
    embedding_config_hash,
)
from providers.openrouter.errors import OpenRouterResponseError

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image-payload"
DIMENSION = 4


def fixed_clock() -> str:
    return "2026-08-07T00:00:00+00:00"


def client_config(**overrides: object) -> OpenRouterClientConfig:
    values: dict[str, object] = {
        "max_concurrency": 2,
        "requests_per_second": 10_000.0,
        "timeout_seconds": 5.0,
        "retry_limit": 2,
    }
    values.update(overrides)
    return OpenRouterClientConfig(**values)  # type: ignore[arg-type]


def make_client(handler, **overrides: object) -> OpenRouterClient:
    return OpenRouterClient(
        client_config(**overrides),
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )


def embedding_slot_config(slot: str = "text_encoder") -> EmbeddingSlotConfig:
    return EmbeddingSlotConfig(
        slot=slot, model="test/embed", dimension=DIMENSION, encoding_format="float"
    )


def embedding_for(item: object) -> list[float]:
    """A deterministic, input-derived, non-normalized embedding row."""
    if isinstance(item, str):
        text = item
    else:
        # The multimodal item shape, checked live 2026-08-08: a
        # content wrapper around one image_url entry.
        text = item["content"][0]["image_url"]["url"]  # type: ignore[index]
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [1.0 + digest[position] for position in range(DIMENSION)]


def embeddings_response(inputs: list[object]) -> dict[str, object]:
    return {
        "data": [
            {"index": position, "embedding": embedding_for(item)}
            for position, item in enumerate(inputs)
        ],
        "usage": {"total_tokens": 3},
    }


def embeddings_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.read().decode("utf-8"))
    return httpx.Response(200, json=embeddings_response(body["input"]))


def make_text_encoder(tmp_path: Path, handler=embeddings_handler, **kwargs) -> OpenRouterTextEncoder:
    client = make_client(handler)
    return OpenRouterTextEncoder(
        embedding_slot_config(), client, tmp_path / "cache", clock=fixed_clock, **kwargs
    )


def expected_unit_row(item: object) -> np.ndarray:
    row = np.asarray(embedding_for(item), dtype=np.float64)
    return (row / np.linalg.norm(row)).astype(np.float32)


def test_text_post_body_shape_and_url_path(tmp_path: Path) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        captured.append((request.url.path, body))
        return httpx.Response(200, json=embeddings_response(body["input"]))

    encoder = make_text_encoder(tmp_path, handler)
    encoder.encode_texts(["alpha", "beta"])
    path, body = captured[0]
    assert path.endswith("/embeddings")
    assert body == {
        "model": "test/embed",
        "input": ["alpha", "beta"],
        "encoding_format": "float",
    }


def test_image_post_body_uses_content_blocks(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        captured.append(body)
        return httpx.Response(200, json=embeddings_response(body["input"]))

    client = make_client(handler)
    encoder = OpenRouterImageEncoder(
        embedding_slot_config("image_encoder"), client, tmp_path / "cache", clock=fixed_clock
    )
    encoder.encode_images([PNG_BYTES])
    uri = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
    assert captured[0]["input"] == [
        {"content": [{"type": "image_url", "image_url": {"url": uri}}]}
    ]


def test_130_misses_batch_into_three_posts(tmp_path: Path) -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        batch_sizes.append(len(body["input"]))
        return httpx.Response(200, json=embeddings_response(body["input"]))

    encoder = make_text_encoder(tmp_path, handler)
    texts = [f"text number {number}" for number in range(130)]
    result = encoder.encode_texts(texts)
    assert encoder.post_count == 3
    assert batch_sizes == [EMBEDDING_BATCH_SIZE, EMBEDDING_BATCH_SIZE, 2]
    assert result.shape == (130, DIMENSION)


def test_byte_budget_splits_batches(tmp_path: Path) -> None:
    batch_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        batch_sizes.append(len(body["input"]))
        return httpx.Response(200, json=embeddings_response(body["input"]))

    encoder = make_text_encoder(tmp_path, handler)
    # Three 3 MB texts: the third text pushes one POST above the byte
    # budget, thus the batches split as two plus one.
    texts = [letter * 3_000_000 for letter in ("a", "b", "c")]
    encoder.encode_texts(texts)
    assert batch_sizes == [2, 1]


def test_per_item_cache_entries_are_written(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    encoder = make_text_encoder(tmp_path)
    encoder.encode_texts(["alpha", "beta"])
    for text in ("alpha", "beta"):
        key = sha256_hex("text:" + text)
        path = response_cache_path(cache_root, encoder.config_hash, key)
        assert path.exists()
        entry = load_cached_response(path)
        assert entry is not None
        assert entry["key"] == key
        assert entry["config_hash"] == encoder.config_hash
        assert entry["model"] == "test/embed"
        assert entry["input_kind"] == "text"
        assert entry["embedding"] == embedding_for(text)
        assert entry["created_at"] == fixed_clock()


def test_second_instance_reads_cache_with_zero_posts(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = make_client(embeddings_handler)
    config = embedding_slot_config()
    first = OpenRouterTextEncoder(config, client, cache_root, clock=fixed_clock)
    result_one = first.encode_texts(["alpha", "beta"])
    assert client.post_count == 1

    second = OpenRouterTextEncoder(config, client, cache_root, clock=fixed_clock)
    result_two = second.encode_texts(["alpha", "beta"])
    assert client.post_count == 1
    assert second.cache_hit_count == 2
    np.testing.assert_array_equal(result_one, result_two)


def test_mixed_hit_miss_posts_only_misses_and_aligns_output(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    inputs_seen: list[list[object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        inputs_seen.append(body["input"])
        return httpx.Response(200, json=embeddings_response(body["input"]))

    client = make_client(handler)
    config = embedding_slot_config()
    first = OpenRouterTextEncoder(config, client, cache_root, clock=fixed_clock)
    first.encode_texts(["alpha", "beta"])

    second = OpenRouterTextEncoder(config, client, cache_root, clock=fixed_clock)
    result = second.encode_texts(["alpha", "gamma", "beta"])
    assert client.post_count == 2
    assert inputs_seen[1] == ["gamma"]
    assert second.cache_hit_count == 2
    np.testing.assert_allclose(result[0], expected_unit_row("alpha"), rtol=1e-6)
    np.testing.assert_allclose(result[1], expected_unit_row("gamma"), rtol=1e-6)
    np.testing.assert_allclose(result[2], expected_unit_row("beta"), rtol=1e-6)


def test_out_of_sequence_index_rows_are_placed_correctly(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        rows = embeddings_response(body["input"])["data"]
        return httpx.Response(
            200, json={"data": list(reversed(rows)), "usage": {"total_tokens": 3}}
        )

    encoder = make_text_encoder(tmp_path, handler)
    result = encoder.encode_texts(["alpha", "beta"])
    np.testing.assert_allclose(result[0], expected_unit_row("alpha"), rtol=1e-6)
    np.testing.assert_allclose(result[1], expected_unit_row("beta"), rtol=1e-6)


def test_duplicate_index_values_raise(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        row = embedding_for(body["input"][0])
        rows = [{"index": 0, "embedding": row}, {"index": 0, "embedding": row}]
        return httpx.Response(200, json={"data": rows})

    encoder = make_text_encoder(tmp_path, handler)
    with pytest.raises(OpenRouterResponseError):
        encoder.encode_texts(["alpha", "beta"])


def test_duplicate_inputs_share_one_post_row(tmp_path: Path) -> None:
    inputs_seen: list[list[object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        inputs_seen.append(body["input"])
        return httpx.Response(200, json=embeddings_response(body["input"]))

    encoder = make_text_encoder(tmp_path, handler)
    result = encoder.encode_texts(["same", "same"])
    assert encoder.post_count == 1
    assert inputs_seen == [["same"]]
    np.testing.assert_array_equal(result[0], result[1])


def test_output_is_unit_norm_float32(tmp_path: Path) -> None:
    encoder = make_text_encoder(tmp_path)
    result = encoder.encode_texts(["alpha", "beta", "gamma"])
    assert result.dtype == np.float32
    assert result.shape == (3, DIMENSION)
    np.testing.assert_allclose(
        np.linalg.norm(result, axis=1), np.ones(3), rtol=1e-6
    )
    np.testing.assert_allclose(result[0], expected_unit_row("alpha"), rtol=1e-6)


def test_dimension_mismatch_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1.0, 2.0, 3.0]}]}
        )

    encoder = make_text_encoder(tmp_path, handler)
    with pytest.raises(OpenRouterResponseError, match="test/embed"):
        encoder.encode_texts(["alpha"])


def test_row_count_mismatch_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        rows = embeddings_response(body["input"])["data"][:1]
        return httpx.Response(200, json={"data": rows})

    encoder = make_text_encoder(tmp_path, handler)
    with pytest.raises(OpenRouterResponseError):
        encoder.encode_texts(["alpha", "beta"])


def test_zero_norm_row_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.0] * DIMENSION}]}
        )

    encoder = make_text_encoder(tmp_path, handler)
    with pytest.raises(OpenRouterResponseError, match="zero norm"):
        encoder.encode_texts(["alpha"])


def test_non_finite_value_raises(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        content = '{"data": [{"index": 0, "embedding": [1.0, NaN, 1.0, 1.0]}]}'
        return httpx.Response(
            200, content=content, headers={"Content-Type": "application/json"}
        )

    encoder = make_text_encoder(tmp_path, handler)
    with pytest.raises(OpenRouterResponseError):
        encoder.encode_texts(["alpha"])


def test_cached_wrong_length_row_raises(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    encoder = make_text_encoder(tmp_path)
    key = sha256_hex("text:alpha")
    path = response_cache_path(cache_root, encoder.config_hash, key)
    path.parent.mkdir(parents=True)
    bad_entry = {
        "key": key,
        "config_hash": encoder.config_hash,
        "model": "test/embed",
        "input_kind": "text",
        "embedding": [1.0, 2.0],
        "created_at": fixed_clock(),
    }
    path.write_text(json.dumps(bad_entry), encoding="utf-8")
    with pytest.raises(OpenRouterResponseError):
        encoder.encode_texts(["alpha"])


def test_empty_input_returns_zeros_with_no_post(tmp_path: Path) -> None:
    encoder = make_text_encoder(tmp_path)
    result = encoder.encode_texts([])
    assert result.shape == (0, DIMENSION)
    assert result.dtype == np.float32
    assert encoder.post_count == 0


def test_text_and_image_slot_hashes_are_different() -> None:
    text_hash = embedding_config_hash(embedding_slot_config("text_encoder"))
    image_hash = embedding_config_hash(embedding_slot_config("image_encoder"))
    assert text_hash != image_hash


def test_retry_on_429_through_post_embeddings() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                429, headers={"Retry-After": "0"}, json={"error": "slow down"}
            )
        body = json.loads(request.read().decode("utf-8"))
        return httpx.Response(200, json=embeddings_response(body["input"]))

    client = make_client(handler)
    result = client.post_embeddings(
        {"model": "test/embed", "input": ["alpha"], "encoding_format": "float"}
    )
    assert client.post_count == 2
    assert result["data"][0]["embedding"] == embedding_for("alpha")
