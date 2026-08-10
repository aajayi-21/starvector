"""Unit tests for the OpenRouter generalizer parse and cache path.

The parse path takes the full response body — a review found a
double-extraction defect here that no test covered, and these cases
pin the contract: plain and fenced bodies parse, one answer becomes
one cache entry, and a warm read makes no post.
"""

import json

from providers.openrouter.generalize import (GeneralizeSlotConfig,
                                             OpenRouterGeneralizer)

CONFIG = GeneralizeSlotConfig(
    slot="generalize", model="test/model",
    template="Broaden: {element}", temperature=0.0, seed=7,
    max_tokens=64, reasoning_enabled=False,
    response_format_mode="json_schema")


class _StubClient:
    """Answers scripted message contents, in post sequence."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.post_count = 0

    def map_requests(self, bodies):
        answers = []
        for _ in bodies:
            self.post_count += 1
            answers.append({
                "choices": [{"message": {"content": self._contents.pop(0)}}],
                "usage": {"total_tokens": 5},
            })
        return answers


def _generalizer(tmp_path, contents):
    client = _StubClient(contents)
    slot = OpenRouterGeneralizer(CONFIG, client, tmp_path,
                                 clock=lambda: "2026-08-10T00:00:00Z")
    return slot, client


def test_a_plain_json_body_parses(tmp_path):
    slot, client = _generalizer(
        tmp_path, [json.dumps({"phrase": "metal instrument"})])
    assert slot.generalize(["trumpet"]) == ["metal instrument"]
    assert client.post_count == 1
    assert slot.cache_hit_count == 0


def test_a_fenced_body_parses(tmp_path):
    fenced = "```json\n" + json.dumps({"phrase": "metal instrument"}) \
        + "\n```"
    slot, _ = _generalizer(tmp_path, [fenced])
    assert slot.generalize(["trumpet"]) == ["metal instrument"]


def test_a_warm_read_makes_no_post(tmp_path):
    first, _ = _generalizer(
        tmp_path, [json.dumps({"phrase": "metal instrument"})])
    first.generalize(["trumpet"])
    second, client = _generalizer(tmp_path, [])
    assert second.generalize(["trumpet"]) == ["metal instrument"]
    assert client.post_count == 0
    assert second.cache_hit_count == 1
