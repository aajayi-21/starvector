"""Offline tests for the OpenRouter providers, with httpx.MockTransport."""

import base64
import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from core.canonical import sha256_hex
from providers.openrouter.cache import load_cached_response, response_cache_path
from providers.openrouter.client import OpenRouterClient, OpenRouterClientConfig
from providers.openrouter.errors import OpenRouterRequestError, OpenRouterResponseError
from providers.openrouter.slots import (
    OpenRouterSalientObjectEstimator,
    OpenRouterSlotConfig,
    OpenRouterTextCoverageEstimator,
    OpenRouterZeroShotImageClassifier,
    slot_config_hash,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image-payload"
PHRASES = ("a photograph", "a diagram", "a map")


def fixed_clock() -> str:
    return "2026-08-06T00:00:00+00:00"


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


def chat_body(content: str) -> dict[str, object]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"total_tokens": 7},
    }


def content_handler(content: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_body(content))

    return handler


def make_slot_config(
    slot: str = "text_coverage",
    tolerance: float | None = None,
    template: str = "Give the fraction.",
) -> OpenRouterSlotConfig:
    return OpenRouterSlotConfig(
        slot=slot,
        model="test/vlm",
        template=template,
        temperature=0.0,
        seed=0,
        max_tokens=512,
        reasoning_enabled=False,
        response_format_mode="json_schema",
        probability_sum_tolerance=tolerance,
    )


def text_estimator(tmp_path: Path, content: str) -> OpenRouterTextCoverageEstimator:
    client = make_client(content_handler(content))
    return OpenRouterTextCoverageEstimator(
        make_slot_config(), client, tmp_path / "cache", clock=fixed_clock
    )


def make_classifier(
    tmp_path: Path, content: str
) -> OpenRouterZeroShotImageClassifier:
    client = make_client(content_handler(content))
    config = make_slot_config(
        "classifier",
        template="Classify the image with the phrases {label_phrases}.",
    )
    return OpenRouterZeroShotImageClassifier(
        config, client, tmp_path / "cache", clock=fixed_clock
    )


def choice_content(label: str, confidence: float) -> str:
    return json.dumps({"label": label, "confidence": confidence})


def test_fraction_parses_to_array(tmp_path: Path) -> None:
    provider = text_estimator(tmp_path, '{"text_area_fraction": 0.03}')
    result = provider.estimate_text_coverage([PNG_BYTES])
    assert result.dtype == np.float32
    assert result.shape == (1,)
    assert result[0] == pytest.approx(0.03)


def test_fraction_out_of_range_raises(tmp_path: Path) -> None:
    provider = text_estimator(tmp_path, '{"text_area_fraction": 1.5}')
    with pytest.raises(OpenRouterResponseError):
        provider.estimate_text_coverage([PNG_BYTES])


def test_missing_fraction_field_raises(tmp_path: Path) -> None:
    provider = text_estimator(tmp_path, '{"wrong_field": 0.5}')
    with pytest.raises(OpenRouterResponseError):
        provider.estimate_text_coverage([PNG_BYTES])


def test_garbage_content_raises(tmp_path: Path) -> None:
    provider = text_estimator(tmp_path, "no json here")
    with pytest.raises(OpenRouterResponseError):
        provider.estimate_text_coverage([PNG_BYTES])


def test_fenced_json_parses(tmp_path: Path) -> None:
    provider = text_estimator(tmp_path, '```json\n{"text_area_fraction": 0.5}\n```')
    result = provider.estimate_text_coverage([PNG_BYTES])
    assert result[0] == pytest.approx(0.5)


def test_salient_object_fraction_parses(tmp_path: Path) -> None:
    client = make_client(content_handler('{"largest_object_fraction": 0.4}'))
    provider = OpenRouterSalientObjectEstimator(
        make_slot_config("object_size"), client, tmp_path / "cache", clock=fixed_clock
    )
    result = provider.estimate_salient_object_fraction([PNG_BYTES])
    assert result.dtype == np.float32
    assert result[0] == pytest.approx(0.4)


def test_unknown_image_magic_bytes_raise(tmp_path: Path) -> None:
    provider = text_estimator(tmp_path, '{"text_area_fraction": 0.1}')
    with pytest.raises(OpenRouterResponseError):
        provider.estimate_text_coverage([b"plain bytes, not an image"])


def test_post_body_carries_pinned_parameters(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode("utf-8")))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=chat_body('{"text_area_fraction": 0.0}'))

    client = make_client(handler)
    provider = OpenRouterTextCoverageEstimator(
        make_slot_config(), client, tmp_path / "cache", clock=fixed_clock
    )
    provider.estimate_text_coverage([PNG_BYTES])
    body = captured[0]
    assert body["model"] == "test/vlm"
    assert body["temperature"] == 0.0
    assert body["seed"] == 0
    assert body["max_tokens"] == 512
    assert body["reasoning"] == {"enabled": False}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    content = body["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Give the fraction."}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_classifier_replaces_label_placeholder_and_sends_enum(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []
    content = choice_content("a photograph", 0.8)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(200, json=chat_body(content))

    client = make_client(handler)
    config = make_slot_config(
        "classifier",
        template="Classify the image with the phrases {label_phrases}.",
    )
    provider = OpenRouterZeroShotImageClassifier(
        config, client, tmp_path / "cache", clock=fixed_clock
    )
    provider.classify([PNG_BYTES], PHRASES)
    instruction = captured[0]["messages"][0]["content"][0]["text"]
    expected = 'Classify the image with the phrases "a photograph", "a diagram", "a map".'
    assert instruction == expected
    schema = captured[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["label"]["enum"] == list(PHRASES)


def test_classifier_choice_becomes_probability_row(tmp_path: Path) -> None:
    provider = make_classifier(tmp_path, choice_content("a photograph", 0.8))
    result = provider.classify([PNG_BYTES], PHRASES)
    assert result.dtype == np.float32
    assert result.shape == (1, 3)
    assert result[0].sum() == pytest.approx(1.0, abs=1e-6)
    assert result[0, 0] == pytest.approx(0.8)
    assert result[0, 1] == pytest.approx(0.1)
    assert int(result[0].argmax()) == 0


def test_classifier_label_out_of_set_raises(tmp_path: Path) -> None:
    provider = make_classifier(tmp_path, choice_content("a sculpture", 0.9))
    with pytest.raises(OpenRouterResponseError):
        provider.classify([PNG_BYTES], PHRASES)


def test_classifier_confidence_out_of_range_raises(tmp_path: Path) -> None:
    provider = make_classifier(tmp_path, choice_content("a photograph", 1.5))
    with pytest.raises(OpenRouterResponseError):
        provider.classify([PNG_BYTES], PHRASES)


def test_classifier_confidence_at_or_below_uniform_raises(tmp_path: Path) -> None:
    # With three labels a confidence of 1/3 cannot win its own row.
    provider = make_classifier(tmp_path, choice_content("a photograph", 1.0 / 3.0))
    with pytest.raises(OpenRouterResponseError):
        provider.classify([PNG_BYTES], PHRASES)


def test_classifier_missing_confidence_raises(tmp_path: Path) -> None:
    provider = make_classifier(tmp_path, '{"label": "a photograph"}')
    with pytest.raises(OpenRouterResponseError):
        provider.classify([PNG_BYTES], PHRASES)


def test_classifier_template_without_placeholder_raises(tmp_path: Path) -> None:
    client = make_client(content_handler("{}"))
    config = make_slot_config("classifier", template="No placeholder.")
    with pytest.raises(ValueError):
        OpenRouterZeroShotImageClassifier(
            config, client, tmp_path / "cache", clock=fixed_clock
        )


def test_first_batch_posts_and_writes_cache(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = make_client(content_handler('{"text_area_fraction": 0.25}'))
    config = make_slot_config()
    first = OpenRouterTextCoverageEstimator(config, client, cache_root, clock=fixed_clock)
    result_one = first.estimate_text_coverage([PNG_BYTES])
    assert client.post_count == 1
    assert first.post_count == 1
    assert first.cache_hit_count == 0

    path = response_cache_path(cache_root, first.config_hash, sha256_hex(PNG_BYTES))
    assert path.exists()
    entry = load_cached_response(path)
    assert entry is not None
    assert entry["key"] == sha256_hex(PNG_BYTES)
    assert entry["config_hash"] == first.config_hash
    assert entry["model"] == "test/vlm"
    assert entry["usage"] == {"total_tokens": 7}
    assert entry["created_at"] == fixed_clock()

    second = OpenRouterTextCoverageEstimator(config, client, cache_root, clock=fixed_clock)
    result_two = second.estimate_text_coverage([PNG_BYTES])
    assert client.post_count == 1
    assert second.cache_hit_count == 1
    assert result_two[0] == result_one[0]


def test_corrupted_cache_entry_raises(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = make_client(content_handler('{"text_area_fraction": 0.25}'))
    provider = OpenRouterTextCoverageEstimator(
        make_slot_config(), client, cache_root, clock=fixed_clock
    )
    path = response_cache_path(cache_root, provider.config_hash, sha256_hex(PNG_BYTES))
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(OpenRouterResponseError):
        provider.estimate_text_coverage([PNG_BYTES])


def test_cached_body_is_validated_again(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = make_client(content_handler('{"text_area_fraction": 0.25}'))
    provider = OpenRouterTextCoverageEstimator(
        make_slot_config(), client, cache_root, clock=fixed_clock
    )
    path = response_cache_path(cache_root, provider.config_hash, sha256_hex(PNG_BYTES))
    path.parent.mkdir(parents=True)
    bad_entry = {
        "key": sha256_hex(PNG_BYTES),
        "config_hash": provider.config_hash,
        "model": "test/vlm",
        "response_body": chat_body('{"text_area_fraction": 7.0}'),
        "usage": None,
        "created_at": fixed_clock(),
    }
    path.write_text(json.dumps(bad_entry), encoding="utf-8")
    with pytest.raises(OpenRouterResponseError):
        provider.estimate_text_coverage([PNG_BYTES])


def test_empty_api_key_raises_at_construction() -> None:
    with pytest.raises(OpenRouterRequestError):
        OpenRouterClient(
            client_config(),
            api_key="",
            transport=httpx.MockTransport(content_handler("{}")),
        )


def test_api_key_is_not_part_of_slot_config_hash(tmp_path: Path) -> None:
    config = make_slot_config()
    handler = content_handler('{"text_area_fraction": 0.1}')
    one = OpenRouterTextCoverageEstimator(
        config,
        OpenRouterClient(
            client_config(), api_key="key-one", transport=httpx.MockTransport(handler)
        ),
        tmp_path / "a",
        clock=fixed_clock,
    )
    two = OpenRouterTextCoverageEstimator(
        config,
        OpenRouterClient(
            client_config(), api_key="key-two", transport=httpx.MockTransport(handler)
        ),
        tmp_path / "b",
        clock=fixed_clock,
    )
    assert one.config_hash == two.config_hash
    assert one.config_hash == slot_config_hash(config)


def test_retry_on_429_then_200_succeeds() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(
                429, headers={"Retry-After": "0"}, json={"error": "slow down"}
            )
        return httpx.Response(200, json=chat_body('{"text_area_fraction": 0.2}'))

    client = make_client(handler)
    result = client.post_chat({"model": "test/vlm"})
    assert client.post_count == 2
    message = result["choices"][0]["message"]
    assert message["content"] == '{"text_area_fraction": 0.2}'


def test_400_raises_with_no_retry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad body"})

    client = make_client(handler)
    with pytest.raises(OpenRouterRequestError):
        client.post_chat({"model": "test/vlm"})
    assert client.post_count == 1


def test_retry_limit_reached_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, headers={"Retry-After": "0"}, json={"error": "boom"})

    client = make_client(handler, retry_limit=1)
    with pytest.raises(OpenRouterRequestError):
        client.post_chat({"model": "test/vlm"})
    assert client.post_count == 2


def test_batch_output_is_index_aligned(tmp_path: Path) -> None:
    image_one = PNG_BYTES + b"-one"
    image_two = PNG_BYTES + b"-two"
    uri_one = "data:image/png;base64," + base64.b64encode(image_one).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        uri = body["messages"][0]["content"][1]["image_url"]["url"]
        fraction = 0.1 if uri == uri_one else 0.9
        return httpx.Response(
            200, json=chat_body(json.dumps({"text_area_fraction": fraction}))
        )

    client = make_client(handler)
    provider = OpenRouterTextCoverageEstimator(
        make_slot_config(), client, tmp_path / "cache", clock=fixed_clock
    )
    result = provider.estimate_text_coverage([image_one, image_two])
    assert client.post_count == 2
    assert result[0] == pytest.approx(0.1)
    assert result[1] == pytest.approx(0.9)


def test_json_object_mode_body(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(200, json=chat_body('{"text_area_fraction": 0.0}'))

    config = make_slot_config()._replace(response_format_mode="json_object")
    client = make_client(handler)
    provider = OpenRouterTextCoverageEstimator(
        config, client, tmp_path / "cache", clock=fixed_clock
    )
    provider.estimate_text_coverage([PNG_BYTES])
    assert captured[0]["response_format"] == {"type": "json_object"}
