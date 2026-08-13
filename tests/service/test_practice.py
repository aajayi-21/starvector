"""Integration: the practice surfaces (spec P5 item B5).

Practice replays revealed day targets, scores through the resident
context, and stores nothing. The section 22 rule this file pins: a
practice answer names no image but the practiced target, and while a
day is open no practice byte moves with the open day's target.
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
    listing = client.get("/api/practice")
    assert listing.status_code == 200
    days = listing.json()["days"]
    assert [row["day"] for row in days] == [DAY]
    record = store.read_day_record(fixture["store"], DAY)
    assert days[0]["target_id"] == record.target_id
    assert days[0]["trial_code"] == record.trial_code


def test_no_revealed_day_gives_one_constant_refusal(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    client = TestClient(create_app(fixture["service_config"]))
    first = client.get("/api/practice")
    again = client.get("/api/practice")
    assert first.status_code == again.status_code == 404
    assert first.content == again.content == b'{"detail":"no revealed day"}'


def test_a_practice_score_runs_offline_and_stores_nothing(
        tmp_path) -> None:
    fixture, client = _revealed_world(tmp_path)
    before = _snapshot(fixture["store"])
    answer = client.post("/api/practice/score",
                         json={"day": DAY, "record": mixed_wire_record()})
    assert answer.status_code == 200
    body = answer.json()
    assert body["day"] == DAY
    record = store.read_day_record(fixture["store"], DAY)
    assert body["target_id"] == record.target_id
    assert 0.0 <= body["trial"]["p"] <= 1.0
    assert body["target_position"] >= 1
    assert len(body["ranking_head"]) == 10
    for row in body["ranking_head"]:
        assert set(row) == {"position", "fused", "is_target"}
    assert sum(1 for row in body["ranking_head"] if row["is_target"]) <= 1
    assert body["report"]
    assert {"atom_id", "atom_text", "element", "weight", "similarity",
            "rarity"} == set(body["report"][0])
    # The stored trial row holds the same record against the same
    # target - the practice numbers must agree with it.
    row = store.read_json_or_none(
        store.trial_row_path(fixture["store"], DAY, "ade"))
    assert body["trial"] == {key: row[key] for key in
                             ("p", "decoy_count", "beaten", "tied",
                              "target_rank")}
    # Ephemeral: the store is byte-for-byte as it was.
    assert _snapshot(fixture["store"]) == before


def test_a_practice_answer_names_no_foreign_image(tmp_path) -> None:
    fixture, client = _revealed_world(tmp_path)
    record = store.read_day_record(fixture["store"], DAY)
    answer = client.post("/api/practice/score",
                         json={"day": DAY, "record": mixed_wire_record()})
    text = answer.text
    for image_id in fixture["image_ids"]:
        if image_id == record.target_id:
            continue
        assert image_id not in text


def test_one_constant_refusal_for_each_unplayable_day(tmp_path) -> None:
    fixture, client = _revealed_world(tmp_path)
    # A second day, left open. The open day and the unknown day
    # cover the two refusal classes the endpoint folds into one
    # body.
    assert client.post("/api/day/open").status_code == 200
    open_day_date = store.latest_day(fixture["store"])
    bodies = set()
    for day in ("1999-01-01", open_day_date, "not-a-date"):
        answer = client.post("/api/practice/score",
                             json={"day": day,
                                   "record": mixed_wire_record()})
        assert answer.status_code == 404
        bodies.add(answer.content)
    assert bodies == {b'{"detail":"not a practice day"}'}


def test_the_refusal_shapes_mirror_the_submission_gate(tmp_path) -> None:
    fixture, client = _revealed_world(tmp_path)
    malformed = client.post("/api/practice/score", content=b"not json",
                            headers={"Content-Type": "application/json"})
    assert malformed.status_code == 400
    assert malformed.json()["cause"] == "bad-shape"
    empty = {"impressions": [], "canvas_strokes": [], "groups": [],
             "relations": [], "pasted_text": None}
    unscoreable = client.post("/api/practice/score",
                              json={"day": DAY, "record": empty})
    assert unscoreable.status_code == 400
    assert unscoreable.json()["cause"] == "no-scoreable-atom"
    flooded = mixed_wire_record()
    flooded["impressions"] = [f"impression {n}" for n in range(70)]
    gated = client.post("/api/practice/score",
                        json={"day": DAY, "record": flooded})
    assert gated.status_code == 400
    assert gated.json()["cause"] == "atom-count"


def test_practice_bytes_do_not_vary_with_the_open_target(
        tmp_path) -> None:
    # The R4 walk: two worlds with an equal revealed history and
    # different OPEN targets must give equal practice bytes.
    answers = {}
    for name, seed in (("one", "1" * 32), ("two", "2" * 32)):
        fixture, client = _revealed_world(tmp_path / name)
        open_day(fixture["service_config"], date="2026-08-14",
                 clock=lambda: FIXED_CLOCK, pick_seed=seed,
                 secret="c" * 64)
        listing = client.get("/api/practice")
        scored = client.post("/api/practice/score",
                             json={"day": DAY,
                                   "record": mixed_wire_record()})
        # The trial code is day-level randomness, not a function of
        # the target - normalize it out before the compare.
        listed = listing.json()
        for row in listed["days"]:
            row.pop("trial_code")
        answers[name] = (json.dumps(listed, sort_keys=True),
                         scored.content)
        open_record = store.read_day_record(fixture["store"],
                                            "2026-08-14")
        revealed = store.read_day_record(fixture["store"], DAY)
        if open_record.target_id != revealed.target_id:
            # The open target can align with the revealed one (R6
            # picks from the full pool) - the id is then public
            # through the reveal, not through practice.
            assert open_record.target_id not in answers[name][0]
            assert open_record.target_id.encode() not in answers[name][1]
    assert answers["one"] == answers["two"]
