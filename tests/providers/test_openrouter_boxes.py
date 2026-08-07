"""Offline tests for the OpenRouter box detector slot, with httpx.MockTransport."""

import base64
import json
from pathlib import Path

import httpx
import pytest

from core.canonical import canonical_json, sha256_hex
from providers.openrouter.boxes import (
    BOXES_MAX_TOKENS,
    BoxSlotConfig,
    OpenRouterElementBoxDetector,
    box_config_hash,
)
from providers.openrouter.cache import load_cached_response, response_cache_path
from providers.openrouter.client import OpenRouterClient, OpenRouterClientConfig
from providers.openrouter.errors import OpenRouterResponseError
from providers.protocols import Box

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image-payload"
ELEMENTS = ("a tree", "a bench")


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


def make_box_config(
    template: str = "Locate these elements: {element_list}.",
) -> BoxSlotConfig:
    return BoxSlotConfig(
        slot="element_boxes",
        model="test/vlm",
        template=template,
        temperature=0.0,
        seed=0,
        max_tokens=BOXES_MAX_TOKENS,
        reasoning_enabled=False,
        response_format_mode="json_schema",
    )


def boxes_content(payload: dict[str, object]) -> str:
    return json.dumps(payload)


def valid_payload() -> dict[str, object]:
    return {
        "a tree": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.5, "y_max": 0.9},
        "a bench": None,
    }


def make_detector(tmp_path: Path, content: str) -> OpenRouterElementBoxDetector:
    client = make_client(content_handler(content))
    return OpenRouterElementBoxDetector(
        make_box_config(), client, tmp_path / "cache", clock=fixed_clock
    )


def cache_key(image_bytes: bytes, elements: tuple[str, ...]) -> str:
    image_id = sha256_hex(image_bytes)
    return sha256_hex(image_id + ":" + sha256_hex(canonical_json(list(elements))))


def test_schema_keys_equal_query_and_schema_is_strict(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(200, json=chat_body(boxes_content(valid_payload())))

    client = make_client(handler)
    detector = OpenRouterElementBoxDetector(
        make_box_config(), client, tmp_path / "cache", clock=fixed_clock
    )
    detector.detect_boxes([PNG_BYTES], [ELEMENTS])
    body = captured[0]
    assert body["model"] == "test/vlm"
    assert body["max_tokens"] == BOXES_MAX_TOKENS
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    schema = body["response_format"]["json_schema"]["schema"]
    assert sorted(schema["properties"]) == sorted(ELEMENTS)
    assert schema["required"] == list(ELEMENTS)
    assert schema["additionalProperties"] is False
    variants = schema["properties"]["a tree"]["anyOf"]
    assert variants[1] == {"type": "null"}
    box_schema = variants[0]
    assert sorted(box_schema["properties"]) == ["x_max", "x_min", "y_max", "y_min"]
    for field in ("x_min", "y_min", "x_max", "y_max"):
        assert box_schema["properties"][field] == {
            "type": "number", "minimum": 0, "maximum": 1,
        }
    assert sorted(box_schema["required"]) == ["x_max", "x_min", "y_max", "y_min"]
    assert box_schema["additionalProperties"] is False


def test_placeholder_is_replaced_with_quoted_elements(tmp_path: Path) -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(200, json=chat_body(boxes_content(valid_payload())))

    client = make_client(handler)
    detector = OpenRouterElementBoxDetector(
        make_box_config(), client, tmp_path / "cache", clock=fixed_clock
    )
    detector.detect_boxes([PNG_BYTES], [ELEMENTS])
    instruction = captured[0]["messages"][0]["content"][0]["text"]
    assert instruction == 'Locate these elements: "a tree", "a bench".'


def test_null_becomes_none_and_box_becomes_box(tmp_path: Path) -> None:
    detector = make_detector(tmp_path, boxes_content(valid_payload()))
    result = detector.detect_boxes([PNG_BYTES], [ELEMENTS])
    assert result == [
        {
            "a tree": Box(x_min=0.1, y_min=0.2, x_max=0.5, y_max=0.9),
            "a bench": None,
        }
    ]


def test_inverted_box_raises(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["a tree"] = {"x_min": 0.7, "y_min": 0.2, "x_max": 0.5, "y_max": 0.9}
    detector = make_detector(tmp_path, boxes_content(payload))
    with pytest.raises(OpenRouterResponseError, match="a tree"):
        detector.detect_boxes([PNG_BYTES], [ELEMENTS])


def test_out_of_range_value_raises(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["a tree"] = {"x_min": 0.1, "y_min": 0.2, "x_max": 1.5, "y_max": 0.9}
    detector = make_detector(tmp_path, boxes_content(payload))
    with pytest.raises(OpenRouterResponseError):
        detector.detect_boxes([PNG_BYTES], [ELEMENTS])


def test_missing_element_key_raises(tmp_path: Path) -> None:
    detector = make_detector(tmp_path, boxes_content({"a tree": None}))
    with pytest.raises(OpenRouterResponseError):
        detector.detect_boxes([PNG_BYTES], [ELEMENTS])


def test_extra_element_key_raises(tmp_path: Path) -> None:
    payload = valid_payload()
    payload["a cloud"] = None
    detector = make_detector(tmp_path, boxes_content(payload))
    with pytest.raises(OpenRouterResponseError):
        detector.detect_boxes([PNG_BYTES], [ELEMENTS])


def test_changed_element_list_posts_again_and_writes_second_entry(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        elements = body["response_format"]["json_schema"]["schema"]["required"]
        payload = {element: None for element in elements}
        return httpx.Response(200, json=chat_body(boxes_content(payload)))

    client = make_client(handler)
    config = make_box_config()
    detector = OpenRouterElementBoxDetector(config, client, cache_root, clock=fixed_clock)
    detector.detect_boxes([PNG_BYTES], [ELEMENTS])
    assert client.post_count == 1

    # The same query reads the cache and makes no new POST.
    again = OpenRouterElementBoxDetector(config, client, cache_root, clock=fixed_clock)
    again.detect_boxes([PNG_BYTES], [ELEMENTS])
    assert client.post_count == 1
    assert again.cache_hit_count == 1

    # A different element list is a new key: one new POST, a second file.
    other_elements = ("a tree", "a cloud")
    again.detect_boxes([PNG_BYTES], [other_elements])
    assert client.post_count == 2
    first_path = response_cache_path(
        cache_root, detector.config_hash, cache_key(PNG_BYTES, ELEMENTS)
    )
    second_path = response_cache_path(
        cache_root, detector.config_hash, cache_key(PNG_BYTES, other_elements)
    )
    assert first_path.exists()
    assert second_path.exists()
    assert first_path != second_path


def test_cache_entry_carries_query_provenance_fields(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    detector = make_detector(tmp_path, boxes_content(valid_payload()))
    detector.detect_boxes([PNG_BYTES], [ELEMENTS])
    path = response_cache_path(
        cache_root, detector.config_hash, cache_key(PNG_BYTES, ELEMENTS)
    )
    entry = load_cached_response(path)
    assert entry is not None
    assert entry["key"] == cache_key(PNG_BYTES, ELEMENTS)
    assert entry["image_id"] == sha256_hex(PNG_BYTES)
    assert entry["element_list_hash"] == sha256_hex(canonical_json(list(ELEMENTS)))
    assert entry["elements"] == list(ELEMENTS)
    assert entry["model"] == "test/vlm"
    assert entry["created_at"] == fixed_clock()


def test_error_names_image_id(tmp_path: Path) -> None:
    detector = make_detector(tmp_path, "no json here")
    with pytest.raises(OpenRouterResponseError, match=sha256_hex(PNG_BYTES)):
        detector.detect_boxes([PNG_BYTES], [ELEMENTS])


def test_alignment_across_two_images_with_different_lists(tmp_path: Path) -> None:
    image_one = PNG_BYTES + b"-one"
    image_two = PNG_BYTES + b"-two"
    uri_one = "data:image/png;base64," + base64.b64encode(image_one).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode("utf-8"))
        uri = body["messages"][0]["content"][1]["image_url"]["url"]
        if uri == uri_one:
            payload: dict[str, object] = {
                "a tree": {"x_min": 0.0, "y_min": 0.0, "x_max": 0.5, "y_max": 0.5}
            }
        else:
            payload = {"a bench": None, "a cloud": None}
        return httpx.Response(200, json=chat_body(boxes_content(payload)))

    client = make_client(handler)
    detector = OpenRouterElementBoxDetector(
        make_box_config(), client, tmp_path / "cache", clock=fixed_clock
    )
    result = detector.detect_boxes(
        [image_one, image_two], [("a tree",), ("a bench", "a cloud")]
    )
    assert client.post_count == 2
    assert result[0] == {"a tree": Box(0.0, 0.0, 0.5, 0.5)}
    assert result[1] == {"a bench": None, "a cloud": None}


def test_template_without_placeholder_raises_at_construction(tmp_path: Path) -> None:
    client = make_client(content_handler("{}"))
    with pytest.raises(ValueError):
        OpenRouterElementBoxDetector(
            make_box_config(template="No placeholder."),
            client,
            tmp_path / "cache",
            clock=fixed_clock,
        )


def test_duplicate_elements_in_one_query_raise(tmp_path: Path) -> None:
    detector = make_detector(tmp_path, boxes_content(valid_payload()))
    with pytest.raises(ValueError):
        detector.detect_boxes([PNG_BYTES], [("a tree", "a tree")])


def test_misaligned_inputs_raise(tmp_path: Path) -> None:
    detector = make_detector(tmp_path, boxes_content(valid_payload()))
    with pytest.raises(ValueError):
        detector.detect_boxes([PNG_BYTES], [ELEMENTS, ELEMENTS])


def test_empty_query_gives_empty_mapping_with_no_post(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    detector = make_detector(tmp_path, boxes_content(valid_payload()))
    result = detector.detect_boxes([PNG_BYTES], [()])
    assert result == [{}]
    assert detector.post_count == 0
    assert not cache_root.exists()


def test_template_change_moves_config_hash() -> None:
    base = make_box_config()
    other = make_box_config(template="A different instruction: {element_list}.")
    assert box_config_hash(base) != box_config_hash(other)
