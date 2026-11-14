"""Offline tests for the one-POST screener (spec PP1 B7)."""

import json
from pathlib import Path

import httpx
import numpy as np
import pytest

from providers.openrouter.client import OpenRouterClient, OpenRouterClientConfig
from providers.openrouter.errors import OpenRouterResponseError
from providers.openrouter.screener import (OpenRouterScreener,
                                           ScreenerSlotConfig,
                                           screener_config_hash)

PNG = b"\x89PNG\r\n\x1a\n" + b"screen-me"
LABELS = ("photograph", "diagram", "painting or artwork")
ANSWER = {
    "text_area_fraction": 0.02,
    "label": "photograph",
    "confidence": 0.9,
    "largest_object_fraction": 0.4,
    "person_role": "in_scene",
}


def slot_config(**overrides: object) -> ScreenerSlotConfig:
    values: dict = {
        "slot": "screener", "model": "m", "template": "Pick from {label_phrases}.",
        "labels": LABELS, "temperature": 0.0, "seed": 0, "max_tokens": 512,
        "reasoning_enabled": False, "response_format_mode": "json_schema",
        "input_canvas_px": None,
    }
    values.update(overrides)
    return ScreenerSlotConfig(**values)


class Recorder:
    def __init__(self, answer: dict | None = None) -> None:
        self.bodies: list[dict] = []
        self._answer = answer if answer is not None else ANSWER

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            self.bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [
                {"message": {"content": json.dumps(self._answer)}}]})
        return httpx.MockTransport(handle)


def screener(recorder: Recorder, root: Path, **overrides: object) -> OpenRouterScreener:
    prepare = overrides.pop("prepare", None)
    client = OpenRouterClient(
        OpenRouterClientConfig(max_concurrency=1, requests_per_second=10_000.0,
                               timeout_seconds=5.0, retry_limit=0),
        "test-key", transport=recorder.transport())
    return OpenRouterScreener(slot_config(**overrides), client, root, prepare=prepare)


def test_the_four_answers_come_from_one_post(tmp_path: Path) -> None:
    recorder = Recorder()
    provider = screener(recorder, tmp_path)
    np.testing.assert_allclose(provider.estimate_text_coverage([PNG]), [0.02])
    classes = provider.classify([PNG], LABELS)
    np.testing.assert_allclose(classes.sum(axis=1), [1.0])
    assert int(classes.argmax()) == 0
    np.testing.assert_allclose(provider.estimate_salient_object_fraction([PNG]), [0.4])
    np.testing.assert_array_equal(provider.person_is_main_subject([PNG]), [0.0])
    assert len(recorder.bodies) == 1
    assert provider.cache_hit_count == 3


def test_the_schema_holds_the_closed_sets(tmp_path: Path) -> None:
    recorder = Recorder()
    screener(recorder, tmp_path).estimate_text_coverage([PNG])
    schema = recorder.bodies[0]["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["label"]["enum"] == list(LABELS)
    assert schema["properties"]["person_role"]["enum"] == [
        "none", "in_scene", "main_subject"]
    text = recorder.bodies[0]["messages"][0]["content"][0]["text"]
    assert '"painting or artwork"' in text


@pytest.mark.parametrize(("role", "flag"), [
    ("none", 0.0), ("in_scene", 0.0), ("main_subject", 1.0)])
def test_only_the_main_subject_role_raises_the_flag(
        tmp_path: Path, role: str, flag: float) -> None:
    provider = screener(Recorder({**ANSWER, "person_role": role}), tmp_path)
    assert provider.person_is_main_subject([PNG]).tolist() == [flag]


@pytest.mark.parametrize("change", [
    {"person_role": "maybe"},
    {"text_area_fraction": 1.5},
    {"label": "cloud"},
    {"largest_object_fraction": "half"},
])
def test_a_bad_answer_raises(tmp_path: Path, change: dict) -> None:
    provider = screener(Recorder({**ANSWER, **change}), tmp_path)
    with pytest.raises(OpenRouterResponseError):
        provider.estimate_text_coverage([PNG])


def test_a_missing_field_raises(tmp_path: Path) -> None:
    answer = {key: value for key, value in ANSWER.items() if key != "person_role"}
    with pytest.raises(OpenRouterResponseError):
        screener(Recorder(answer), tmp_path).estimate_text_coverage([PNG])


def test_a_different_label_set_is_a_wiring_fault(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="labels"):
        screener(Recorder(), tmp_path).classify([PNG], ("photograph",))


def test_the_post_holds_the_prepared_image_and_the_key_stays_raw(tmp_path: Path) -> None:
    recorder = Recorder()
    prepared = b"\x89PNG\r\n\x1a\n" + b"smaller"
    provider = screener(recorder, tmp_path, prepare=lambda _: prepared,
                        input_canvas_px=512)
    provider.estimate_text_coverage([PNG])
    url = recorder.bodies[0]["messages"][0]["content"][1]["image_url"]["url"]
    import base64
    assert url.endswith(base64.b64encode(prepared).decode())
    # A second instance on the same cache makes no POST for the raw bytes.
    second = Recorder()
    screener(second, tmp_path, prepare=lambda _: prepared,
             input_canvas_px=512).estimate_text_coverage([PNG])
    assert second.bodies == []


def test_a_template_with_no_label_place_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="label_phrases"):
        screener(Recorder(), tmp_path, template="No labels here.")


def test_the_hash_moves_with_each_field() -> None:
    base = slot_config()
    others = [base._replace(labels=LABELS[:2]), base._replace(template="{label_phrases}!"),
              base._replace(input_canvas_px=512), base._replace(model="other")]
    assert len({screener_config_hash(item) for item in [base, *others]}) == 5


class SequenceRecorder(Recorder):
    """One answer for each POST, in the sequence of the POSTs."""

    def __init__(self, answers: list[dict]) -> None:
        super().__init__()
        self._answers = answers

    def transport(self) -> httpx.MockTransport:
        def handle(request: httpx.Request) -> httpx.Response:
            answer = self._answers[len(self.bodies)]
            self.bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [
                {"message": {"content": json.dumps(answer)}}]})
        return httpx.MockTransport(handle)


def test_a_bad_answer_keeps_the_good_answers_of_its_group(tmp_path: Path) -> None:
    # A group of three with a refused answer in the middle. The two good
    # answers have their cost, thus they must be in the cache when the
    # error stops the group.
    images = [PNG + b"-a", PNG + b"-b", PNG + b"-c"]
    refused = {**ANSWER, "person_role": "maybe"}
    first = SequenceRecorder([ANSWER, refused, ANSWER])
    with pytest.raises(OpenRouterResponseError, match="person_role is not in the set"):
        screener(first, tmp_path).estimate_text_coverage(images)
    assert len(first.bodies) == 3

    second = SequenceRecorder([ANSWER])
    provider = screener(second, tmp_path)
    np.testing.assert_allclose(provider.estimate_text_coverage(images),
                               [0.02, 0.02, 0.02])
    assert len(second.bodies) == 1
    assert provider.cache_hit_count == 2


@pytest.mark.parametrize("stated", ["photograph", "diagram"])
def test_a_contradictory_label_gives_a_row_with_no_winner(
        tmp_path: Path, stated: str) -> None:
    # Confidence at or below 1/L: the stated label does not win its own
    # row. The owner ruling of 2026-11-11 (spec PP1 section 5d) makes
    # that a row with no winner, not an error, and s04 puts the image
    # out. The answer is in the cache, thus a second read makes no POST.
    recorder = Recorder({**ANSWER, "label": stated, "confidence": 0.05})
    provider = screener(recorder, tmp_path)
    row = provider.classify([PNG], LABELS)[0]
    np.testing.assert_allclose(row.sum(), 1.0)
    assert np.count_nonzero(row == row.max()) == 2
    assert row[LABELS.index(stated)] < row.max()
    provider.classify([PNG], LABELS)
    assert len(recorder.bodies) == 1
    assert provider.cache_hit_count == 1
