"""Offline tests for the OpenRouter describer slot, with httpx.MockTransport."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from core.canonical import sha256_hex
from providers.openrouter.cache import load_cached_response, response_cache_path
from providers.openrouter.client import OpenRouterClient, OpenRouterClientConfig
from providers.openrouter.describer import (
    DESCRIBER_MAX_TOKENS,
    DescriberSlotConfig,
    OpenRouterVlmDescriber,
    describer_config_hash,
)
from providers.openrouter.errors import OpenRouterResponseError
from providers.protocols import ElementResponse

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image-payload"


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


def chat_body(content: str) -> dict[str, object]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"total_tokens": 7},
    }


def content_handler(content: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=chat_body(content))

    return handler


def make_describer_config(
    template: str = "Describe the image with the fixed element schema.",
    **overrides: object,
) -> DescriberSlotConfig:
    values: dict[str, object] = {
        "slot": "describer",
        "model": "test/vlm",
        "template": template,
        "temperature": 0.0,
        "seed": 0,
        "max_tokens": DESCRIBER_MAX_TOKENS,
        "reasoning_enabled": False,
        "response_format_mode": "json_schema",
        "objects_count": 3,
        "materials_count": 3,
        "colors_count": 3,
        "shapes_count": 2,
        "ambience_count": 3,
    }
    values.update(overrides)
    return DescriberSlotConfig(**values)  # type: ignore[arg-type]


def element_payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "objects": ["oak tree", "bench", "gravel path"],
        "materials": ["wood", "stone", "iron"],
        "colors": ["green", "brown", "grey"],
        "shapes": ["vertical", "rounded"],
        "scale": "room-scale",
        "setting": "outdoor park",
        "ambience": ["calm", "sunlit", "open"],
    }
    values.update(overrides)
    return values


def element_content(**overrides: object) -> str:
    return json.dumps(element_payload(**overrides))


def make_describer(tmp_path: Path, content: str) -> OpenRouterVlmDescriber:
    client = make_client(content_handler(content))
    return OpenRouterVlmDescriber(
        make_describer_config(), client, tmp_path / "cache", clock=fixed_clock
    )


def test_post_body_carries_pinned_parameters_and_strict_schema(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode("utf-8")))
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(200, json=chat_body(element_content()))

    client = make_client(handler)
    provider = OpenRouterVlmDescriber(
        make_describer_config(), client, tmp_path / "cache", clock=fixed_clock
    )
    provider.describe_images([PNG_BYTES])
    body = captured[0]
    assert body["model"] == "test/vlm"
    assert body["temperature"] == 0.0
    assert body["seed"] == 0
    assert body["max_tokens"] == DESCRIBER_MAX_TOKENS
    assert body["reasoning"] == {"enabled": False}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    schema = body["response_format"]["json_schema"]["schema"]
    assert sorted(schema["properties"]) == sorted(
        ["objects", "materials", "colors", "shapes", "scale", "setting", "ambience"]
    )
    assert schema["properties"]["objects"] == {
        "type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 3,
    }
    assert schema["properties"]["shapes"]["minItems"] == 2
    assert schema["properties"]["shapes"]["maxItems"] == 2
    assert schema["properties"]["scale"] == {"type": "string"}
    assert schema["properties"]["setting"] == {"type": "string"}
    assert sorted(schema["required"]) == sorted(schema["properties"])
    assert schema["additionalProperties"] is False
    content = body["messages"][0]["content"]
    assert content[0]["text"] == "Describe the image with the fixed element schema."
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_valid_response_parses_to_element_response(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, element_content())
    result = provider.describe_images([PNG_BYTES])
    assert result == [
        ElementResponse(
            objects=("oak tree", "bench", "gravel path"),
            materials=("wood", "stone", "iron"),
            colors=("green", "brown", "grey"),
            shapes=("vertical", "rounded"),
            scale="room-scale",
            setting="outdoor park",
            ambience=("calm", "sunlit", "open"),
        )
    ]


def test_fenced_json_parses(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, "```json\n" + element_content() + "\n```")
    result = provider.describe_images([PNG_BYTES])
    assert result[0].scale == "room-scale"


def test_empty_string_entry_raises(tmp_path: Path) -> None:
    content = element_content(objects=["oak tree", "", "gravel path"])
    provider = make_describer(tmp_path, content)
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_whitespace_only_setting_raises(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, element_content(setting="   "))
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_count_violation_raises(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, element_content(objects=["oak tree", "bench"]))
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_missing_key_raises(tmp_path: Path) -> None:
    payload = element_payload()
    del payload["ambience"]
    provider = make_describer(tmp_path, json.dumps(payload))
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_extra_key_raises(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, element_content(mood="wistful"))
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_array_scale_raises(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, element_content(scale=["room-scale"]))
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_non_string_entry_raises(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, element_content(colors=["green", 7, "grey"]))
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_garbage_content_raises(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, "no json here")
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_error_names_image_hash_and_model(tmp_path: Path) -> None:
    provider = make_describer(tmp_path, element_content(scale=""))
    with pytest.raises(OpenRouterResponseError, match=sha256_hex(PNG_BYTES)) as excinfo:
        provider.describe_images([PNG_BYTES])
    assert "test/vlm" in str(excinfo.value)


def test_first_batch_posts_and_writes_cache(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = make_client(content_handler(element_content()))
    config = make_describer_config()
    first = OpenRouterVlmDescriber(config, client, cache_root, clock=fixed_clock)
    result_one = first.describe_images([PNG_BYTES])
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

    second = OpenRouterVlmDescriber(config, client, cache_root, clock=fixed_clock)
    result_two = second.describe_images([PNG_BYTES])
    assert client.post_count == 1
    assert second.cache_hit_count == 1
    assert result_two == result_one


def test_corrupted_cache_entry_raises(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = make_client(content_handler(element_content()))
    provider = OpenRouterVlmDescriber(
        make_describer_config(), client, cache_root, clock=fixed_clock
    )
    path = response_cache_path(cache_root, provider.config_hash, sha256_hex(PNG_BYTES))
    path.parent.mkdir(parents=True)
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(OpenRouterResponseError):
        provider.describe_images([PNG_BYTES])


def test_cached_count_violation_is_validated_again(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    client = make_client(content_handler(element_content()))
    provider = OpenRouterVlmDescriber(
        make_describer_config(), client, cache_root, clock=fixed_clock
    )
    path = response_cache_path(cache_root, provider.config_hash, sha256_hex(PNG_BYTES))
    path.parent.mkdir(parents=True)
    bad_entry = {
        "key": sha256_hex(PNG_BYTES),
        "config_hash": provider.config_hash,
        "model": "test/vlm",
        "response_body": chat_body(element_content(objects=["only one"])),
        "usage": None,
        "created_at": fixed_clock(),
    }
    path.write_text(json.dumps(bad_entry), encoding="utf-8")
    with pytest.raises(OpenRouterResponseError, match="cached image"):
        provider.describe_images([PNG_BYTES])


def test_two_image_batch_output_is_index_aligned(tmp_path: Path) -> None:
    image_one = PNG_BYTES + b"-one"
    image_two = PNG_BYTES + b"-two"
    uri_one = "data:image/png;base64," + base64.b64encode(image_one).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        uri = body["messages"][0]["content"][1]["image_url"]["url"]
        scale = "close-up" if uri == uri_one else "landscape"
        return httpx.Response(200, json=chat_body(element_content(scale=scale)))

    client = make_client(handler)
    provider = OpenRouterVlmDescriber(
        make_describer_config(), client, tmp_path / "cache", clock=fixed_clock
    )
    result = provider.describe_images([image_one, image_two])
    assert client.post_count == 2
    assert result[0].scale == "close-up"
    assert result[1].scale == "landscape"


def test_template_and_count_changes_move_config_hash() -> None:
    base = make_describer_config()
    assert describer_config_hash(base) == describer_config_hash(make_describer_config())
    retemplated = make_describer_config(template="A different instruction.")
    recounted = make_describer_config(objects_count=4)
    assert describer_config_hash(retemplated) != describer_config_hash(base)
    assert describer_config_hash(recounted) != describer_config_hash(base)


def test_api_key_is_not_part_of_config_hash(tmp_path: Path) -> None:
    config = make_describer_config()
    handler = content_handler(element_content())
    one = OpenRouterVlmDescriber(
        config,
        OpenRouterClient(
            client_config(), api_key="key-one", transport=httpx.MockTransport(handler)
        ),
        tmp_path / "a",
        clock=fixed_clock,
    )
    two = OpenRouterVlmDescriber(
        config,
        OpenRouterClient(
            client_config(), api_key="key-two", transport=httpx.MockTransport(handler)
        ),
        tmp_path / "b",
        clock=fixed_clock,
    )
    assert one.config_hash == two.config_hash
    assert one.config_hash == describer_config_hash(config)
