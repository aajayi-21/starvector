"""Integration: the spec S2 wire additions.

The new surfaces are read-only against the store and follow the
constant-refusal discipline. This file pins their shapes. The R3
walk and the R4 two-world tests hold the leakage rules.
"""

import dataclasses
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
