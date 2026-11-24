"""The tool that measures the cost of one instant send (spec IM1 IM1.2).

Offline: a mock transport stands in for the provider and gives the
token counts and the cost with each answer. No key and no network.
"""

import json
from pathlib import Path

import httpx
import pytest

from conftest import build_direct_prepared_pool, scoring_config_dict

from providers.openrouter.client import (OpenRouterClient,
                                         OpenRouterClientConfig)
from tools import instant_cost

DIMENSION = 4
# What the mock provider asks for one input of a POST.
TOKENS_OF_ONE_INPUT = 250
COST_OF_ONE_INPUT = 0.0002


def _handler(with_cost: bool = True):
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        count = len(body["input"])
        usage = {"prompt_tokens": TOKENS_OF_ONE_INPUT * count,
                 "total_tokens": TOKENS_OF_ONE_INPUT * count,
                 "note": "text that is not a number"}
        if with_cost:
            usage["cost"] = COST_OF_ONE_INPUT * count
        return httpx.Response(200, json={
            "data": [{"index": at, "embedding": [1.0 + at, 2.0, 3.0, 4.0]}
                     for at in range(count)],
            "usage": usage})

    return handle


def _client(handler) -> instant_cost.UsageClient:
    return instant_cost.UsageClient(OpenRouterClient(
        OpenRouterClientConfig(max_concurrency=1,
                               requests_per_second=10_000.0,
                               timeout_seconds=5.0, retry_limit=0),
        api_key="test-key", transport=httpx.MockTransport(handler)))


def _config(tmp_path: Path, provider: str = "openrouter") -> Path:
    prepared = build_direct_prepared_pool(tmp_path / "pool", 8)
    model = "test/embed" if provider == "openrouter" else None
    document = scoring_config_dict(
        prepared["prep_record_path"],
        **{"providers.sketch_encoder.provider": provider,
           "providers.sketch_encoder.model": model,
           "providers.sketch_encoder.dimension": DIMENSION,
           "providers.text_encoder.provider": provider,
           "providers.text_encoder.model": model,
           "providers.text_encoder.dimension": DIMENSION})
    path = tmp_path / "scoring-config.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_each_sample_is_a_paid_post_with_its_usage(tmp_path) -> None:
    client = _client(_handler())
    samples = instant_cost.measure(_config(tmp_path), client,
                                   tmp_path / "cache")
    by_name = {sample.name: sample for sample in samples}
    assert list(by_name) == ["sketch and words", "words alone",
                             "sketch alone"]
    # Words alone is one POST of the text slot, with three inputs.
    words = by_name["words alone"]
    assert words.posts == 1
    assert words.usage["total_tokens"] == 3 * TOKENS_OF_ONE_INPUT
    assert words.cost == pytest.approx(3 * COST_OF_ONE_INPUT)
    # A sketch alone is one POST of the sketch slot.
    assert by_name["sketch alone"].posts == 1
    # A sketch with words uses the two slots.
    assert by_name["sketch and words"].posts == 2
    assert by_name["sketch and words"].cost > words.cost / 3
    assert all(sample.seconds >= 0.0 for sample in samples)
    # A value that is text is not in the sum.
    assert "note" not in words.usage
    assert client.post_count == 4


def test_a_second_measure_with_the_same_cache_posts_nothing(
        tmp_path) -> None:
    """The cache is why the tool gets a new, empty one: a warm cache
    gives no POST and thus no cost to measure."""
    config = _config(tmp_path)
    client = _client(_handler())
    instant_cost.measure(config, client, tmp_path / "cache")
    again = instant_cost.measure(config, client, tmp_path / "cache")
    assert [sample.posts for sample in again] == [0, 0, 0]
    assert all(sample.cost is None for sample in again)


def test_the_report_gives_the_cap_of_a_budget(tmp_path) -> None:
    samples = instant_cost.measure(_config(tmp_path), _client(_handler()),
                                   tmp_path / "cache")
    largest = max(sample.cost for sample in samples)
    lines = instant_cost.report_lines(samples, budget_usd=2.0)
    assert f"largest cost of one send: USD {largest:.6f}" in lines
    assert lines[-1] == ("instant_day_cap for USD 2 on one date: "
                         f"{instant_cost.cap_for_budget(2.0, largest)}")
    assert any(line.startswith("words alone: 1 POST(s)") for line in lines)
    # With no budget the report has no cap line.
    assert not any("instant_day_cap" in line
                   for line in instant_cost.report_lines(samples, None))


def test_a_provider_with_no_cost_number_gives_no_cap(tmp_path) -> None:
    samples = instant_cost.measure(
        _config(tmp_path), _client(_handler(with_cost=False)),
        tmp_path / "cache")
    lines = instant_cost.report_lines(samples, budget_usd=2.0)
    assert all(sample.cost is None for sample in samples)
    assert "tokens, no cost number" in lines[0]
    assert not any("instant_day_cap" in line for line in lines)
    assert "activity page" in lines[-1]


def test_a_config_of_a_different_provider_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError, match="OpenRouter slots"):
        instant_cost.measure(_config(tmp_path, provider="fake"),
                             _client(_handler()), tmp_path / "cache")


@pytest.mark.parametrize("budget, cost, cap", [
    (1.0, 0.0004, 2500), (1.0, 0.0003, 3333), (0.5, 1.0, 0),
    (10.0, 0.001, 10000)])
def test_the_cap_is_the_budget_divided_by_the_cost(budget: float,
                                                   cost: float,
                                                   cap: int) -> None:
    assert instant_cost.cap_for_budget(budget, cost) == cap


@pytest.mark.parametrize("budget, cost", [(0.0, 0.001), (1.0, 0.0),
                                          (-1.0, 0.001), (1.0, -0.5)])
def test_a_budget_or_a_cost_of_zero_gives_no_cap(budget: float,
                                                 cost: float) -> None:
    with pytest.raises(ValueError):
        instant_cost.cap_for_budget(budget, cost)


def test_the_command_refuses_with_no_key(tmp_path, monkeypatch,
                                         capsys) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert instant_cost.main(["--config", str(_config(tmp_path))]) == 1
    assert "API key" in capsys.readouterr().err
