"""The send count of the day view (spec H1 section 3)."""

import time

from fastapi.testclient import TestClient
from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

DAY = "2026-08-12"


def _world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    client = TestClient(create_app(fixture["service_config"]))
    return fixture, client


def _write_send(root, player: str) -> None:
    store.write_once_json(
        store.submission_path(root, DAY, player),
        {"day": DAY, "player": player, "trial_id": f"trial-{player}",
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})


def test_an_empty_day_counts_zero(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    assert store.count_submissions(fixture["store"], DAY) == 0


def test_the_count_skips_a_write_in_progress(tmp_path) -> None:
    fixture, _ = _world(tmp_path)
    root = fixture["store"]
    for player in ("ada", "bo", "cy"):
        _write_send(root, player)
    stray = store.submission_path(root, DAY, "dee").with_suffix(".json.tmp")
    stray.write_text("{}")
    assert store.count_submissions(root, DAY) == 3
    assert len(store.list_submissions(root, DAY)) == 3


def test_the_day_view_holds_the_count_in_each_status(tmp_path) -> None:
    fixture, client = _world(tmp_path)
    assert client.get("/api/day").json()["sends"] == 0

    sent = client.post(f"/api/submission?day={DAY}", json=mixed_wire_record())
    assert sent.status_code == 200
    assert client.get("/api/day").json()["sends"] == 1

    _write_send(fixture["store"], "other-player")
    assert client.get("/api/day").json()["sends"] == 2

    close_day(fixture["service_config"], providers=fixture["providers"],
              clock=lambda: FIXED_CLOCK)
    assert client.get("/api/day").json()["sends"] == 2
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    view = client.get("/api/day").json()
    assert view["status"] == "revealed"
    assert view["sends"] == 2


def test_the_scan_of_3000_sends_is_fast(tmp_path) -> None:
    """The measure of spec H1 section 7, with a loose bound.

    The bound is a guard against a walk that sorts or reads files, not
    a benchmark: the scan reads names only.
    """
    fixture = build_service_fixture(tmp_path)
    folder = store.day_dir(fixture["store"], DAY) / "submissions"
    folder.mkdir(parents=True)
    for index in range(3000):
        (folder / f"player-{index}.json").write_text("{}")
    start = time.perf_counter()
    assert store.count_submissions(fixture["store"], DAY) == 3000
    assert time.perf_counter() - start < 0.5
