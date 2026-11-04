"""The load tool (spec PL1 section 9): the arithmetic, and one short run.

No GPU and no network. The run starts the server on a loopback port.
"""

from tools import load


def _level(*, rate: float, p95_ms: float = 100.0, errors: int = 0,
           requests: int = 10) -> load.LevelResult:
    return load.LevelResult(concurrency=1, seconds=1.0, requests=requests,
                            errors=errors, rate=rate, p50_ms=1.0,
                            p95_ms=p95_ms, p99_ms=p95_ms)


def test_the_percentile_is_nearest_rank() -> None:
    assert load.percentile([], 0.95) == 0.0
    assert load.percentile([5.0], 0.95) == 5.0
    assert load.percentile([float(at) for at in range(100)], 0.95) == 95.0


def test_a_level_needs_no_errors_and_the_budget() -> None:
    assert load.passes(_level(rate=10.0), 500.0)
    assert not load.passes(_level(rate=10.0, errors=1), 500.0)
    assert not load.passes(_level(rate=10.0, p95_ms=501.0), 500.0)
    assert not load.passes(_level(rate=0.0, requests=0), 500.0)


def test_the_capacity_is_the_last_passing_level_before_the_first_miss() -> None:
    """The rate falls as concurrency rises, and the capacity reads the
    rate at the highest concurrency that holds the budget."""
    levels = [_level(rate=200.0), _level(rate=100.0),
              _level(rate=300.0, p95_ms=900.0), _level(rate=999.0)]
    assert load.capacity(levels, 500.0, 2.0) == (50, 100.0)


def test_the_capacity_is_zero_when_the_first_level_misses() -> None:
    assert load.capacity([_level(rate=100.0, errors=1)], 500.0, 2.0) \
        == (0, 0.0)


def test_the_model_rate_follows_the_model() -> None:
    assert load.player_rate() == sum(load.PLAYER_MODEL.values()) / 600.0


def test_a_short_run_gives_a_number() -> None:
    report = load.run_load(players=6, pool=40, seeded_days=1, levels=[1, 2],
                           seconds=1.0, budget_ms=5000.0)
    assert report["active_players"] > 0
    assert len(report["levels"]) == 2
    assert all(level["errors"] == 0 for level in report["levels"])
    assert report["close_seconds"] >= 0.0
    assert report["world"]["providers"] == "fake"
