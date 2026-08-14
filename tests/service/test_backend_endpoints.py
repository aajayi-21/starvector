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
