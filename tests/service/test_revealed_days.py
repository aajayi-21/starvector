"""Integration: the listing of the revealed days.

This was the listing of the practice screen (spec P5 item B5). The
instant trial replaced practice (spec IM1 section 15), and the listing
stays for the row of days. The rule this file pins: while a day is
open, no byte of the listing moves with the target of that day.
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

DAY = "2026-08-13"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def _revealed_world(tmp_path, *, pick_seed="a" * 32, played=True):
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed=pick_seed,
             secret="b" * 64)
    if played:
        store.write_once_json(
            store.submission_path(fixture["store"], DAY, "ade"),
            {"day": DAY, "player": "ade", "trial_id": "f" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    return fixture, TestClient(create_app(fixture["service_config"]))


def test_the_listing_holds_revealed_days_alone(tmp_path) -> None:
    fixture, client = _revealed_world(tmp_path)
    # A second, open day: it must stay out of the listing.
    opened = client.post("/api/day/open")
    assert opened.status_code == 200
    listing = client.get("/api/days")
    assert listing.status_code == 200
    days = listing.json()["days"]
    assert [row["day"] for row in days] == [DAY]
    record = store.read_day_record(fixture["store"], DAY)
    assert days[0]["target_id"] == record.target_id
    assert days[0]["trial_code"] == record.trial_code


def test_no_revealed_day_gives_one_constant_refusal(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    client = TestClient(create_app(fixture["service_config"]))
    first = client.get("/api/days")
    again = client.get("/api/days")
    assert first.status_code == again.status_code == 404
    assert first.content == again.content == b'{"detail":"no revealed day"}'


def test_the_listing_does_not_follow_the_open_target(tmp_path) -> None:
    # The R4 walk: two worlds with an equal revealed history and
    # different OPEN targets must give an equal listing.
    answers = {}
    for name, seed in (("one", "1" * 32), ("two", "2" * 32)):
        fixture, client = _revealed_world(tmp_path / name)
        open_day(fixture["service_config"], date="2026-08-14",
                 clock=lambda: FIXED_CLOCK, pick_seed=seed,
                 secret="c" * 64)
        listed = client.get("/api/days").json()
        # The trial code is day-level randomness, not a function of
        # the target - normalize it out before the compare.
        for row in listed["days"]:
            row.pop("trial_code")
        answers[name] = json.dumps(listed, sort_keys=True)
        open_record = store.read_day_record(fixture["store"],
                                            "2026-08-14")
        revealed = store.read_day_record(fixture["store"], DAY)
        if open_record.target_id != revealed.target_id:
            assert open_record.target_id not in answers[name]
    assert answers["one"] == answers["two"]


def test_the_practice_paths_are_gone(tmp_path) -> None:
    """Spec IM1 ruling 3: the instant trial replaced practice."""
    _, client = _revealed_world(tmp_path)
    assert client.get("/api/practice").status_code == 404
    assert client.post("/api/practice/score", json={
        "day": DAY, "record": mixed_wire_record()}).status_code == 404
