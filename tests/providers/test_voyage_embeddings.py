"""Offline tests for the Voyage encoders, with httpx.MockTransport."""

import base64
import json
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

from providers.voyage import wiring
from providers.voyage.client import VoyageClient, VoyageClientConfig
from providers.voyage.embeddings import (EMBEDDING_BATCH_SIZE,
                                         VoyageImageEncoder, VoyageSlotConfig,
                                         VoyageTextEncoder,
                                         voyage_config_hash)
from providers.voyage.errors import (VoyageRequestError, VoyageResponseError,
                                     VoyageTimeoutError)

DIMENSION = 4
INSTRUCTION = "Represent this photograph."


def png(width: int = 8, height: int = 4, shade: int = 0) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (shade, 0, 0)).save(buffer, "PNG")
    return buffer.getvalue()


def encoded(values: list[float]) -> str:
    return base64.b64encode(np.asarray(values, dtype="<f4").tobytes()).decode()


def answer(body: dict, values: list[float] | None = None) -> dict:
    row = values if values is not None else [3.0, 0.0, 4.0, 0.0]
    return {
        "object": "list",
        "data": [{"object": "embedding", "embedding": encoded(row), "index": i}
                 for i in range(len(body["inputs"]))],
        "model": body["model"],
        "usage": {"text_tokens": 5, "image_pixels": 32, "total_tokens": 6},
    }


class Recorder:
    """A transport that records bodies and answers through a handler."""

    def __init__(self, handler=None) -> None:
        self.bodies: list[dict] = []
        self.headers: list[httpx.Headers] = []
        self.paths: list[str] = []
        self._handler = handler

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.bodies.append(body)
            self.headers.append(request.headers)
            self.paths.append(request.url.path)
            if self._handler is not None:
                return self._handler(body, len(self.bodies))
            return httpx.Response(200, json=answer(body))
        return httpx.MockTransport(handle)


def client(recorder: Recorder, **overrides: object) -> VoyageClient:
    values: dict = {"requests_per_minute": 10**9, "tokens_per_minute": 10**12,
                    "timeout_seconds": 5.0, "retry_limit": 2}
    values.update(overrides)
    return VoyageClient(VoyageClientConfig(**values), "test-key",
                        transport=recorder.transport(), sleep=lambda _: None)


def image_encoder(recorder: Recorder, root: Path, instruction: str | None = None,
                  **client_overrides: object) -> VoyageImageEncoder:
    return VoyageImageEncoder(
        VoyageSlotConfig("image_encoder", "voyage-multimodal-3.5", DIMENSION,
                         instruction),
        client(recorder, **client_overrides), root,
        clock=lambda: "2026-11-03T00:00:00+00:00")


def text_encoder(recorder: Recorder, root: Path) -> VoyageTextEncoder:
    return VoyageTextEncoder(
        VoyageSlotConfig("text_encoder", "voyage-multimodal-3.5", DIMENSION),
        client(recorder), root, clock=lambda: "2026-11-03T00:00:00+00:00")


def test_the_request_holds_the_ruled_fields(tmp_path: Path) -> None:
    recorder = Recorder()
    image_encoder(recorder, tmp_path).encode_images([png()])
    body = recorder.bodies[0]
    assert recorder.paths == ["/v1/multimodalembeddings"]
    assert recorder.headers[0]["authorization"] == "Bearer test-key"
    assert body["truncation"] is False
    assert body["input_type"] is None
    assert body["output_encoding"] == "base64"
    assert body["model"] == "voyage-multimodal-3.5"
    assert "output_dimension" not in body


def test_the_instruction_goes_first_in_one_item(tmp_path: Path) -> None:
    recorder = Recorder()
    image = png()
    image_encoder(recorder, tmp_path, INSTRUCTION).encode_images([image])
    content = recorder.bodies[0]["inputs"][0]["content"]
    assert content[0] == {"type": "text", "text": INSTRUCTION}
    assert content[1]["type"] == "image_base64"
    prefix = "data:image/png;base64,"
    assert content[1]["image_base64"] == \
        prefix + base64.b64encode(image).decode()


def test_a_plain_image_item_has_one_entry(tmp_path: Path) -> None:
    recorder = Recorder()
    image_encoder(recorder, tmp_path).encode_images([png()])
    content = recorder.bodies[0]["inputs"][0]["content"]
    assert [entry["type"] for entry in content] == ["image_base64"]


def test_a_text_item_has_one_text_entry(tmp_path: Path) -> None:
    recorder = Recorder()
    text_encoder(recorder, tmp_path).encode_texts(["a red door"])
    assert recorder.bodies[0]["inputs"] == [
        {"content": [{"type": "text", "text": "a red door"}]}]


def test_the_output_is_unit_norm_float32(tmp_path: Path) -> None:
    vectors = image_encoder(Recorder(), tmp_path).encode_images([png()])
    assert vectors.dtype == np.float32
    assert vectors.shape == (1, DIMENSION)
    np.testing.assert_allclose(vectors[0], [0.6, 0.0, 0.8, 0.0], atol=1e-6)


def test_a_cache_hit_gives_the_same_bytes_and_no_post(tmp_path: Path) -> None:
    recorder = Recorder()
    encoder = image_encoder(recorder, tmp_path)
    first = encoder.encode_images([png()])
    second = encoder.encode_images([png()])
    assert len(recorder.bodies) == 1
    assert encoder.cache_hit_count == 1
    assert first.tobytes() == second.tobytes()


def test_the_cache_entry_is_base64_not_floats(tmp_path: Path) -> None:
    image_encoder(Recorder(), tmp_path).encode_images([png()])
    entry = json.loads(next(tmp_path.rglob("*.json")).read_text())
    assert "embedding" not in entry
    assert entry["embedding_base64"] == encoded([3.0, 0.0, 4.0, 0.0])


def test_a_repeated_input_posts_one_time(tmp_path: Path) -> None:
    recorder = Recorder()
    vectors = image_encoder(recorder, tmp_path).encode_images([png(), png()])
    assert len(recorder.bodies[0]["inputs"]) == 1
    assert vectors.shape == (2, DIMENSION)


def test_the_hash_moves_on_each_field_that_moves_a_vector() -> None:
    base = VoyageSlotConfig("image_encoder", "voyage-multimodal-3.5", 1024)
    others = [base._replace(slot="sketch_encoder"),
              base._replace(model="voyage-multimodal-3"),
              base._replace(dimension=2048),
              base._replace(instruction=INSTRUCTION)]
    hashes = {voyage_config_hash(item) for item in [base, *others]}
    assert len(hashes) == 5


@pytest.mark.parametrize("data", [
    [],
    [{"index": 0}],
    [{"index": 1, "embedding": encoded([1.0, 0.0, 0.0, 0.0])}],
    [{"index": 0, "embedding": [1.0, 0.0, 0.0, 0.0]}],
    [{"index": 0, "embedding": "not base64!"}],
    [{"index": 0, "embedding": encoded([1.0, 0.0])}],
    [{"index": 0, "embedding": encoded([float("nan"), 0.0, 0.0, 0.0])}],
    [{"index": 0, "embedding": encoded([0.0, 0.0, 0.0, 0.0])}],
])
def test_a_bad_response_raises(tmp_path: Path, data: list) -> None:
    recorder = Recorder(lambda body, _: httpx.Response(
        200, json={"data": data, "usage": {}}))
    with pytest.raises(VoyageResponseError):
        image_encoder(recorder, tmp_path).encode_images([png()])


def test_a_corrupt_cache_entry_raises(tmp_path: Path) -> None:
    image_encoder(Recorder(), tmp_path).encode_images([png()])
    next(tmp_path.rglob("*.json")).write_text("{not json")
    with pytest.raises(VoyageResponseError):
        image_encoder(Recorder(), tmp_path).encode_images([png()])


def test_a_refusal_is_not_retried(tmp_path: Path) -> None:
    recorder = Recorder(lambda body, _: httpx.Response(400, text="too long"))
    with pytest.raises(VoyageRequestError, match="too long"):
        image_encoder(recorder, tmp_path).encode_images([png()])
    assert len(recorder.bodies) == 1


def test_a_429_retries_and_then_succeeds(tmp_path: Path) -> None:
    def handler(body: dict, count: int) -> httpx.Response:
        if count == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=answer(body))
    recorder = Recorder(handler)
    vectors = image_encoder(recorder, tmp_path).encode_images([png()])
    assert len(recorder.bodies) == 2
    assert vectors.shape == (1, DIMENSION)


def test_retries_stop_at_the_limit(tmp_path: Path) -> None:
    recorder = Recorder(lambda body, _: httpx.Response(503))
    with pytest.raises(VoyageRequestError, match="after 3 tries"):
        image_encoder(recorder, tmp_path).encode_images([png()])
    assert len(recorder.bodies) == 3


def test_a_timed_out_batch_splits_in_half(tmp_path: Path) -> None:
    def handler(body: dict, _: int) -> httpx.Response:
        if len(body["inputs"]) > 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, json=answer(body))
    recorder = Recorder(handler)
    images = [png(shade=i) for i in range(2)]
    vectors = image_encoder(recorder, tmp_path, retry_limit=0).encode_images(images)
    assert vectors.shape == (2, DIMENSION)
    assert [len(body["inputs"]) for body in recorder.bodies] == [2, 1, 1]


def test_a_single_item_timeout_raises(tmp_path: Path) -> None:
    def handler(body: dict, _: int) -> httpx.Response:
        raise httpx.ReadTimeout("slow")
    with pytest.raises(VoyageTimeoutError):
        image_encoder(Recorder(handler), tmp_path, retry_limit=0
                      ).encode_images([png()])


def test_a_batch_splits_by_count(tmp_path: Path) -> None:
    recorder = Recorder()
    images = [png(shade=i) for i in range(EMBEDDING_BATCH_SIZE + 1)]
    image_encoder(recorder, tmp_path).encode_images(images)
    assert [len(body["inputs"]) for body in recorder.bodies] == \
        [EMBEDDING_BATCH_SIZE, 1]


def test_a_batch_splits_by_estimated_tokens(tmp_path: Path) -> None:
    recorder = Recorder()
    # 560 * 56 pixels is 56 tokens, thus two images fit a limit of 120
    # and a third starts a new POST.
    images = [png(560, 56, shade=i) for i in range(3)]
    image_encoder(recorder, tmp_path, tokens_per_minute=120).encode_images(images)
    assert [len(body["inputs"]) for body in recorder.bodies] == [2, 1]


def test_the_client_paces_by_tokens(tmp_path: Path) -> None:
    now = [0.0]
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    recorder = Recorder()
    paced = VoyageClient(
        VoyageClientConfig(requests_per_minute=10**9, tokens_per_minute=600,
                           timeout_seconds=5.0, retry_limit=0),
        "test-key", transport=recorder.transport(),
        clock=lambda: now[0], sleep=sleep)
    body = {"model": "m", "inputs": []}
    paced.post_embeddings(body, 100)
    paced.post_embeddings(body, 100)
    assert sum(waits) == pytest.approx(10.0)


def test_usage_accumulates(tmp_path: Path) -> None:
    encoder = image_encoder(Recorder(), tmp_path)
    encoder.encode_images([png(shade=1)])
    encoder.encode_images([png(shade=2)])
    assert encoder.usage.image_pixels == 64
    assert encoder.usage.text_tokens == 10


def test_a_text_slot_refuses_an_instruction(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="instructions"):
        VoyageTextEncoder(
            VoyageSlotConfig("text_encoder", "m", DIMENSION, INSTRUCTION),
            client(Recorder()), tmp_path)


def test_an_unknown_media_type_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="media type"):
        image_encoder(Recorder(), tmp_path).encode_images([b"not an image"])


def test_an_empty_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(VoyageRequestError, match="VOYAGE_API_KEY"):
        wiring.client_from_environment()


def test_the_environment_moves_the_account_limits(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")
    monkeypatch.setenv("VOYAGE_TOKENS_PER_MINUTE", "10000")
    assert wiring.client_from_environment().tokens_per_minute == 10_000
    monkeypatch.setenv("VOYAGE_TOKENS_PER_MINUTE", "many")
    with pytest.raises(ValueError, match="VOYAGE_TOKENS_PER_MINUTE"):
        wiring.client_from_environment()
