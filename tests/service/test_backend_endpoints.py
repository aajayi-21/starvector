"""Integration: the spec S2 wire additions.

The new surfaces are read-only against the store and follow the
constant-refusal discipline. This file pins their shapes. The R3
walk and the R4 two-world tests hold the leakage rules.
"""

import dataclasses
import json
from pathlib import Path

from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture

from service.day import open_day
from service.server import create_app

DAY = "2026-08-12"


def _open_world(tmp_path, *, closes_at_utc=None):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    if closes_at_utc is not None:
        config = dataclasses.replace(config, closes_at_utc=closes_at_utc)
        fixture["service_config"] = config
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    return fixture, TestClient(create_app(config))


def test_closes_at_serves_the_configured_time_while_open(
        tmp_path: Path) -> None:
    fixture, client = _open_world(tmp_path, closes_at_utc="22:00")
    view = client.get("/api/day").json()
    assert view["closes_at"] == f"{DAY}T22:00:00+00:00"


def test_closes_at_is_null_without_the_config_or_after_close(
        tmp_path: Path) -> None:
    from service.day import close_day

    fixture, client = _open_world(tmp_path)
    assert client.get("/api/day").json()["closes_at"] is None

    timed, timed_client = _open_world(tmp_path / "timed",
                                      closes_at_utc="22:00")
    close_day(timed["service_config"], clock=lambda: FIXED_CLOCK)
    assert timed_client.get("/api/day").json()["closes_at"] is None


def _played_revealed_world(tmp_path, *, pick_seed="a" * 32,
                           trial_code=None, played=True):
    """A world with one revealed day, played by default."""
    from svc_fixture import mixed_wire_record

    from service import store
    from service.day import close_day, reveal_day

    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed=pick_seed, secret="b" * 64,
             trial_code=trial_code)
    if played:
        store.write_once_json(
            store.submission_path(fixture["store"], DAY, "ade"),
            {"day": DAY, "player": "ade", "trial_id": "f" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    return fixture, TestClient(create_app(config))


def test_a_named_revealed_day_equals_the_latest_day_body(
        tmp_path: Path) -> None:
    fixture, client = _played_revealed_world(tmp_path)
    latest = client.get("/api/reveal")
    named = client.get(f"/api/reveal?day={DAY}")
    assert latest.status_code == named.status_code == 200
    assert latest.content == named.content
    assert named.json()["trial"] is not None


def test_one_constant_refusal_for_each_unrevealed_day(
        tmp_path: Path) -> None:
    fixture, client = _open_world(tmp_path)
    bodies = set()
    for day in ("1999-01-01", DAY, "not-a-date"):
        for _ in range(2):
            answer = client.get(f"/api/reveal?day={day}")
            assert answer.status_code == 404
            bodies.add(answer.content)
    assert bodies == {b'{"detail":"not revealed"}'}


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _run_of_days(tmp_path, days, *, played=None, trial_code=None):
    """A world with a sequence of revealed days, played by default."""
    from svc_fixture import mixed_wire_record

    from service import store
    from service.day import close_day, reveal_day

    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    played = set(days if played is None else played)
    for day in days:
        open_day(config, date=day, clock=lambda: FIXED_CLOCK,
                 pick_seed="a" * 32, secret="b" * 64,
                 trial_code=trial_code)
        if day in played:
            store.write_once_json(
                store.submission_path(fixture["store"], day, "ade"),
                {"day": day, "player": "ade", "trial_id": "f" * 32,
                 "received_at": FIXED_CLOCK,
                 "record": mixed_wire_record()})
        close_day(config, clock=lambda: FIXED_CLOCK)
        reveal_day(config, clock=lambda: FIXED_CLOCK)
    return fixture, TestClient(create_app(config))


def test_history_serves_the_page_numbers_newest_first(
        tmp_path: Path) -> None:
    import math

    from core.aggregate import shrunk_log_theta, skill_summary

    from service import store
    from service.server import POPULATION_MEAN, POPULATION_SPREAD

    days = ("2026-08-10", "2026-08-11", "2026-08-12")
    fixture, client = _run_of_days(tmp_path, days)
    before = _snapshot(fixture["store"])
    body = client.get("/api/history").json()
    assert [row["day"] for row in body["days"]] == list(reversed(days))
    for row in body["days"]:
        stored = store.read_json_or_none(store.trial_row_path(
            fixture["store"], row["day"], "ade"))
        assert row["p"] == stored["p"]
        assert row["target_rank"] == stored["target_rank"]
        assert row["decoy_count"] == stored["decoy_count"]
        record = store.read_day_record(fixture["store"], row["day"])
        assert row["trial_code"] == record.trial_code
        assert set(row) == {"day", "trial_code", "p", "target_rank",
                            "decoy_count"}
    ps = [row["p"] for row in body["days"]]
    summary = skill_summary(ps, unbiased=True)
    assert body["skill"]["theta"] == summary.theta
    assert body["skill"]["evidence_p"] == summary.evidence_p
    assert body["skill"]["n"] == 3
    assert body["skill"]["shrunk"] == math.exp(shrunk_log_theta(
        summary.log_theta, summary.n, POPULATION_MEAN,
        POPULATION_SPREAD))
    # Read-only: the store is byte-equal around the reads (R8).
    assert _snapshot(fixture["store"]) == before


def test_the_skill_value_guards_are_defined_wire_values() -> None:
    from service.server import _skill_value

    assert _skill_value([]) is None
    assert _skill_value([1.0, 1.0]) is None
    single = _skill_value([0.75])
    assert single is not None
    assert single["n"] == 1


def test_history_skips_a_revealed_day_with_no_row(
        tmp_path: Path) -> None:
    days = ("2026-08-10", "2026-08-11")
    fixture, client = _run_of_days(tmp_path, days,
                                   played=["2026-08-11"])
    body = client.get("/api/history").json()
    assert [row["day"] for row in body["days"]] == ["2026-08-11"]
    assert body["skill"]["n"] == 1


def test_the_streak_counts_an_unbroken_run(tmp_path: Path) -> None:
    days = ("2026-08-10", "2026-08-11", "2026-08-12")
    fixture, client = _run_of_days(tmp_path, days)
    assert client.get("/api/me").json()["streak"] == 3


def test_the_streak_stops_at_a_calendar_hole(tmp_path: Path) -> None:
    days = ("2026-08-09", "2026-08-11", "2026-08-12")
    fixture, client = _run_of_days(tmp_path, days)
    # 08-10 has no submission, thus the run is 08-12 and 08-11.
    assert client.get("/api/me").json()["streak"] == 2


def test_the_streak_is_zero_without_a_qualifying_anchor(
        tmp_path: Path) -> None:
    fixture, client = _open_world(tmp_path)
    assert client.get("/api/me").json()["streak"] == 0
    played_none, client_none = _run_of_days(
        tmp_path / "unplayed", ("2026-08-12",), played=[])
    assert client_none.get("/api/me").json()["streak"] == 0


def test_the_leaderboard_serves_the_one_honest_row(
        tmp_path: Path) -> None:
    fixture, client = _played_revealed_world(tmp_path)
    body = client.get(f"/api/leaderboard?day={DAY}").json()
    assert body["day"] == DAY
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["player"] == "ade"
    assert row["streak"] == 1
    assert set(row) == {"player", "p", "target_rank", "decoy_count",
                        "streak"}
    from service import store as store_module

    stored = store_module.read_json_or_none(store_module.trial_row_path(
        fixture["store"], DAY, "ade"))
    assert row["p"] == stored["p"]


def test_the_leaderboard_refuses_unrevealed_days(
        tmp_path: Path) -> None:
    fixture, client = _open_world(tmp_path)
    bodies = set()
    for day in ("1999-01-01", DAY, None):
        path = "/api/leaderboard" if day is None \
            else f"/api/leaderboard?day={day}"
        for _ in range(2):
            answer = client.get(path)
            assert answer.status_code == 404
            bodies.add(answer.content)
    assert bodies == {b'{"detail":"not revealed"}'}


def test_the_leaderboard_holds_no_rows_for_an_unplayed_day(
        tmp_path: Path) -> None:
    fixture, client = _run_of_days(tmp_path, ("2026-08-12",),
                                   played=[])
    body = client.get("/api/leaderboard?day=2026-08-12").json()
    assert body["rows"] == []


def test_the_stored_submission_projects_and_refuses(
        tmp_path: Path) -> None:
    from svc_fixture import mixed_wire_record

    fixture, client = _played_revealed_world(tmp_path)
    body = client.get(f"/api/submission?day={DAY}").json()
    assert set(body) == {"trial_id", "record"}
    assert body["trial_id"] == "f" * 32
    assert body["record"] == mixed_wire_record()
    bodies = set()
    for day in ("1999-01-01", "../escape", "2026-08-13"):
        answer = client.get(f"/api/submission?day={day}")
        assert answer.status_code == 404
        bodies.add(answer.content)
    assert bodies == {b'{"detail":"no submission"}'}


def test_the_new_surfaces_are_byte_stable_across_open_targets(
        tmp_path: Path) -> None:
    # The R4 walk: two worlds with an equal revealed history and
    # different OPEN targets answer byte-equal on each new surface.
    import json

    answers = {}
    for name, seed in (("one", "1" * 32), ("two", "2" * 32)):
        fixture, client = _run_of_days(
            tmp_path / name, (DAY,), trial_code="AAAAAA")
        open_day(fixture["service_config"], date="2026-08-14",
                 clock=lambda: FIXED_CLOCK, pick_seed=seed,
                 secret="c" * 64, trial_code="BBBBBB")
        collected = []
        for path in ("/api/history", f"/api/leaderboard?day={DAY}",
                     f"/api/reveal?day={DAY}",
                     f"/api/submission?day={DAY}", "/api/me"):
            collected.append(client.get(path).content)
        answers[name] = collected
        from service import store as store_module

        open_record = store_module.read_day_record(
            fixture["store"], "2026-08-14")
        revealed = store_module.read_day_record(fixture["store"], DAY)
        if open_record.target_id != revealed.target_id:
            joined = b"|".join(collected)
            assert open_record.target_id.encode() not in joined
    assert answers["one"] == answers["two"]


def test_the_history_page_holds_at_a_degenerate_skill(
        tmp_path: Path) -> None:
    # Each score at 1.0 refuses the aggregation. /api/history serves
    # the defined null and the page says so - neither raises.
    from service import store
    from service.server import _skill_value

    days = ("2026-08-11", "2026-08-12")
    fixture, client = _run_of_days(tmp_path, days)
    for day in days:
        path = store.trial_row_path(fixture["store"], day, "ade")
        row = store.read_json_or_none(path)
        row["p"] = 1.0
        path.write_text(json.dumps(row), encoding="utf-8")
    assert _skill_value([1.0, 1.0]) is None
    body = client.get("/api/history").json()
    assert body["skill"] is None
    assert len(body["days"]) == 2
    dev = TestClient(create_app(fixture["service_config"],
                                dev_mode=True))
    page = dev.get("/history")
    assert page.status_code == 200
    assert "each trial score is 1.0" in page.text
