"""Integration: the HTTP surface (spec S1 sections 9 and 10).

One full day through TestClient with fake providers, the R3 walk in
each status, the byte-equal open page across two targets, and
the refusal shapes.
"""

import json

import pytest
from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

DAY = "2026-08-12"


def _world(tmp_path, *, pick_seed="a" * 32):
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed=pick_seed,
             secret="b" * 64)
    client = TestClient(create_app(fixture["service_config"]))
    return fixture, client


def _close_and_reveal(fixture):
    close_day(fixture["service_config"], providers=fixture["providers"],
              clock=lambda: FIXED_CLOCK)
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)


def test_one_full_day_end_to_end(tmp_path) -> None:
    fixture, client = _world(tmp_path)
    page = client.get("/")
    assert page.status_code == 200
    assert "canvas" in page.text

    day_view = client.get("/api/day").json()
    assert day_view["day"] == DAY
    assert day_view["status"] == "open"
    assert day_view["submitted"] is False
    assert day_view["relation_vocabulary"] == ["left-of", "right-of",
                                               "above", "below"]

    ack = client.post("/api/submission", json=mixed_wire_record())
    assert ack.status_code == 200
    assert set(ack.json()) == {"trial_id", "atom_count"}
    assert ack.json()["atom_count"] == 6

    second = client.post("/api/submission", json=mixed_wire_record())
    assert second.status_code == 409
    assert second.json()["cause"] == "already-submitted"

    _close_and_reveal(fixture)
    record = store.read_day_record(fixture["store"], DAY)

    day_view = client.get("/api/day").json()
    assert day_view["status"] == "revealed"
    assert day_view["target_id"] == record.target_id
    assert day_view["secret"] == record.secret

    reveal = client.get("/api/reveal").json()
    assert reveal["target_id"] == record.target_id
    assert 0.0 <= reveal["trial"]["p"] <= 1.0
    assert reveal["trial"]["target_rank"] >= 1
    assert isinstance(reveal["report"], list)

    image = client.get(f"/image/{record.target_id}")
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG")
    other = [image_id for image_id in fixture["image_ids"]
             if image_id != record.target_id][0]
    assert client.get(f"/image/{other}").status_code == 404

    # The history page is a dev surface (spec S2 B4): the
    # plain client gets the constant refusal, the dev client the
    # page.
    assert client.get("/history").status_code == 404
    dev_client = TestClient(create_app(fixture["service_config"],
                                       dev_mode=True))
    history = dev_client.get("/history")
    assert "DEV-ONLY" in history.text
    assert "skill number" in history.text
    assert DAY in history.text


def test_r3_no_score_bytes_while_open_and_closed(tmp_path) -> None:
    fixture, client = _world(tmp_path)
    client.post("/api/submission", json=mixed_wire_record())
    record = store.read_day_record(fixture["store"], DAY)

    def walk() -> dict[str, bytes]:
        return {path: client.get(path).content
                for path in ("/", "/ui/trial.js", "/api/day",
                             "/api/reveal", "/api/practice",
                             f"/image/{record.target_id}", "/history",
                             "/api/history", "/api/me",
                             f"/api/reveal?day={DAY}",
                             f"/api/leaderboard?day={DAY}",
                             f"/api/submission?day={DAY}")}

    while_open = walk()
    close_day(fixture["service_config"], providers=fixture["providers"],
              clock=lambda: FIXED_CLOCK)
    while_closed = walk()
    for bodies in (while_open, while_closed):
        for path, body in bodies.items():
            text = body.decode("utf-8", errors="ignore")
            assert record.target_id not in text, path
            assert record.secret not in text, path
            if path not in ("/", "/ui/trial.js"):
                # The static page code names the reveal fields it
                # renders - constant strings, not values. The data
                # surfaces must hold no score field at all.
                assert '"p":' not in text, path
                assert "target_rank" not in text, path
    # The refused paths answer with one constant body in each status.
    assert while_open["/api/reveal"] == while_closed["/api/reveal"]
    assert while_open[f"/image/{record.target_id}"] \
        == while_closed[f"/image/{record.target_id}"]
    assert client.get("/api/reveal").status_code == 404
    assert client.get(f"/image/{record.target_id}").status_code == 404


def test_the_open_page_is_byte_identical_across_targets(tmp_path) -> None:
    fixture_one, client_one = _world(tmp_path / "one", pick_seed="1" * 32)
    fixture_two, client_two = _world(tmp_path / "two", pick_seed="2" * 32)
    target_one = store.read_day_record(fixture_one["store"], DAY).target_id
    target_two = store.read_day_record(fixture_two["store"], DAY).target_id
    assert target_one != target_two
    assert client_one.get("/").content == client_two.get("/").content
    assert client_one.get("/ui/trial.js").content \
        == client_two.get("/ui/trial.js").content
    day_one = client_one.get("/api/day").json()
    day_two = client_two.get("/api/day").json()
    assert set(day_one) == set(day_two)
    assert "target_id" not in day_one
    assert "secret" not in day_one


def test_a_gate_violation_names_the_cause(tmp_path) -> None:
    fixture, client = _world(tmp_path)
    flooded = mixed_wire_record()
    flooded["impressions"] = [f"impression {number}"
                              for number in range(70)]
    answer = client.post("/api/submission", json=flooded)
    assert answer.status_code == 400
    assert answer.json()["cause"] == "atom-count"
    malformed = client.post("/api/submission", content=b"not json",
                            headers={"Content-Type": "application/json"})
    assert malformed.status_code == 400
    assert malformed.json()["cause"] == "bad-shape"
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_an_unscoreable_submission_is_refused_before_the_store(
        tmp_path) -> None:
    fixture, client = _world(tmp_path)
    empty = {"impressions": [], "canvas_strokes": [], "groups": [],
             "relations": [], "pasted_text": None}
    answer = client.post("/api/submission", json=empty)
    assert answer.status_code == 400
    assert answer.json()["cause"] == "no-scoreable-atom"
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_post_is_refused_when_the_day_is_closed(tmp_path) -> None:
    fixture, client = _world(tmp_path)
    close_day(fixture["service_config"], providers=fixture["providers"],
              clock=lambda: FIXED_CLOCK)
    answer = client.post("/api/submission", json=mixed_wire_record())
    assert answer.status_code == 409
    assert answer.json()["cause"] == "day-closed"


def test_the_day_view_carries_the_trial_code_front_and_center(
        tmp_path) -> None:
    import re

    fixture, client = _world(tmp_path)
    record = store.read_day_record(fixture["store"], DAY)
    day_view = client.get("/api/day").json()
    assert re.match(r"^[A-Z0-9]{6}$", day_view["trial_code"])
    assert day_view["trial_code"] == record.trial_code
    assert 'id="trial-code"' in client.get("/").text


def test_dev_surfaces_are_constant_404_without_the_flag(tmp_path) -> None:
    fixture, client = _world(tmp_path)
    record = store.read_day_record(fixture["store"], DAY)
    for path in ("/api/dev", "/dev", "/ui/dev.js", "/api/dev/rankings",
                 "/api/dev/submission", "/api/dev/days", "/history"):
        for _ in range(2):
            answer = client.get(path)
            assert answer.status_code == 404, path
            assert answer.content == b'{"detail":"not found"}', path
            assert record.target_id not in answer.text, path


def test_the_console_reads_target_submission_and_preview_rankings(
        tmp_path) -> None:
    fixture, _ = _world(tmp_path)
    record = store.read_day_record(fixture["store"], DAY)
    dev_client = TestClient(create_app(fixture["service_config"],
                                       dev_mode=True))

    dev_view = dev_client.get("/api/dev").json()
    assert dev_view["target_id"] == record.target_id
    assert dev_view["trial_code"] == record.trial_code

    # Each pool image answers in dev mode.
    assert dev_client.get(f"/image/{record.target_id}").status_code == 200
    other = [image_id for image_id in fixture["image_ids"]
             if image_id != record.target_id][0]
    assert dev_client.get(f"/image/{other}").status_code == 200

    # No submission: the console names it.
    assert dev_client.get("/api/dev/submission").json()["cause"] \
        == "no-submission"

    # The player sends on the player page. The console reads it
    # back and ranks it before close - a preview, with no store
    # write but the submission, and the day unmoved.
    ack = dev_client.post("/api/submission", json=mixed_wire_record())
    assert ack.status_code == 200
    stored = dev_client.get("/api/dev/submission").json()
    assert stored["record"] == mixed_wire_record()
    assert stored["trial_id"] == ack.json()["trial_id"]

    preview = dev_client.get("/api/dev/rankings")
    assert preview.status_code == 200
    body = preview.json()
    assert len(body["rankings"]) == len(fixture["image_ids"])
    assert sum(1 for row in body["rankings"] if row["is_target"]) == 1
    # The fifth 14b ruling: each row carries the standardized score
    # of each active weighted channel, and the answer carries the
    # atom report - the console shows what drove a position.
    assert body["channel_names"] == ["element", "outline"]
    for row in body["rankings"]:
        assert set(row["channels"]) == {"element", "outline"}
    assert body["report"]
    assert {"atom_id", "atom_text", "element", "weight", "similarity",
            "rarity"} == set(body["report"][0])
    assert store.read_day_record(fixture["store"], DAY).status == "open"
    assert store.read_json_or_none(
        store.trial_row_path(fixture["store"], DAY, "ade")) is None


def test_a_full_day_runs_through_the_page_endpoints(tmp_path) -> None:
    # The section 14b ruling: the full day lifecycle runs from the
    # page. The fixture scoring config wires fake providers, thus
    # the close endpoint scores offline.
    fixture = build_service_fixture(tmp_path)
    client = TestClient(create_app(fixture["service_config"]))

    assert client.post("/api/day/close").status_code == 409
    opened = client.post("/api/day/open")
    assert opened.status_code == 200
    assert set(opened.json()) == {"day", "trial_code", "commitment"}
    assert client.post("/api/day/open").status_code == 409

    ack = client.post("/api/submission", json=mixed_wire_record())
    assert ack.status_code == 200

    assert client.post("/api/day/reveal").status_code == 409
    closed = client.post("/api/day/close")
    assert closed.status_code == 200
    # The close answer names the row count and no score (R3).
    assert closed.json() == {"trial_rows": 1}

    revealed = client.post("/api/day/reveal")
    assert revealed.status_code == 200
    reveal = client.get("/api/reveal").json()
    assert 0.0 <= reveal["trial"]["p"] <= 1.0


def test_the_console_page_drives_days_back_to_back(tmp_path) -> None:
    # The fourth 14b ruling: /dev is the operator console - no sketch
    # input - and open rolls to the next free date, thus test days
    # run back to back.
    fixture = build_service_fixture(tmp_path)
    dev_client = TestClient(create_app(fixture["service_config"],
                                       dev_mode=True))

    page = dev_client.get("/dev")
    assert page.status_code == 200
    assert "DEV CONSOLE" in page.text
    assert "<canvas" not in page.text
    assert 'id="day-controls"' in page.text
    assert 'id="target-toggle"' in page.text
    # The player page carries no console chrome.
    main_page = dev_client.get("/").text
    assert 'id="day-controls"' not in main_page
    assert "DEV CONSOLE" not in main_page

    assert dev_client.get("/api/dev").json() == {"day": None,
                                                 "status": "none"}
    first = dev_client.post("/api/day/open")
    assert first.status_code == 200
    first_day = first.json()["day"]
    # One active day at a time.
    assert dev_client.post("/api/day/open").status_code == 409

    assert dev_client.post("/api/submission",
                           json=mixed_wire_record()).status_code == 200
    assert dev_client.post("/api/day/close").status_code == 200

    board = dev_client.get("/api/dev/rankings").json()
    day_row = store.read_json_or_none(
        store.trial_row_path(fixture["store"], first_day, "ade"))
    assert board["trial"]["p"] == day_row["p"]
    assert board["trial"]["target_rank"] == day_row["target_rank"]
    assert board["report"] == day_row["report"]

    assert dev_client.post("/api/day/reveal").status_code == 200
    # Open rolls to the next free date.
    second = dev_client.post("/api/day/open")
    assert second.status_code == 200
    second_day = second.json()["day"]
    assert second_day > first_day
    assert store.latest_day(fixture["store"]) == second_day

    # The day browser (fifth 14b ruling): each stored day is
    # readable by name, newest first, and the first day's rankings
    # mark the first day's target.
    days = dev_client.get("/api/dev/days").json()["days"]
    assert [row["day"] for row in days] == [second_day, first_day]
    assert days[1]["submitted"] is True
    assert days[0]["submitted"] is False
    first_record = store.read_day_record(fixture["store"], first_day)
    assert days[1]["trial_code"] == first_record.trial_code
    assert days[1]["target_id"] == first_record.target_id
    browsed = dev_client.get(f"/api/dev/rankings?day={first_day}").json()
    target_rows = [row for row in browsed["rankings"] if row["is_target"]]
    assert [row["image_id"] for row in target_rows] \
        == [first_record.target_id]
    stored = dev_client.get(f"/api/dev/submission?day={first_day}").json()
    assert stored["record"] == mixed_wire_record()
    assert dev_client.get(f"/api/dev/submission?day={second_day}"
                          ).json()["cause"] == "no-submission"
    unknown = dev_client.get("/api/dev/rankings?day=1999-01-01")
    assert unknown.status_code == 404
    assert unknown.json()["cause"] == "no-such-day"


def test_an_empty_store_answers_with_constants(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    client = TestClient(create_app(fixture["service_config"]))
    assert client.get("/api/day").status_code == 404
    assert client.get("/api/day").content \
        == b'{"detail":"no day open"}'
    assert client.post("/api/submission",
                       json=mixed_wire_record()).status_code == 404


def test_the_resident_context_wires_one_time(tmp_path, monkeypatch) -> None:
    # P5 R1: the dev surfaces and the close endpoint read one
    # resident context - the wire runs one time for the process,
    # also when two threadpool handlers race the first use.
    import threading
    import time

    from service import scoring as service_scoring

    fixture, _ = _world(tmp_path)
    client = TestClient(create_app(fixture["service_config"],
                                   dev_mode=True))
    client.post("/api/submission", json=mixed_wire_record())

    calls: list[str] = []
    original = service_scoring.wire_for_close

    def slow_wire(config, config_path, data_root, providers=None):
        calls.append(config_path)
        time.sleep(0.2)
        return original(config, config_path, data_root, providers)

    monkeypatch.setattr(service_scoring, "wire_for_close", slow_wire)

    answers = []

    def hit():
        answers.append(client.get("/api/dev/rankings").status_code)

    first = threading.Thread(target=hit)
    second = threading.Thread(target=hit)
    first.start(); second.start()
    first.join(); second.join()
    assert answers == [200, 200]
    assert len(calls) == 1
    # The next answer reads the kept context - no new wire.
    assert client.get("/api/dev/rankings").status_code == 200
    assert len(calls) == 1
    assert calls[0] == fixture["service_config"].scoring_config
