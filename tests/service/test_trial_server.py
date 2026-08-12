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

    history = client.get("/history")
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
                             "/api/reveal",
                             f"/image/{record.target_id}", "/history")}

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
    for _ in range(2):
        answer = client.get("/api/dev")
        assert answer.status_code == 404
        assert answer.content == b'{"detail":"not found"}'
        assert record.target_id not in answer.text
    score = client.post("/api/dev/score", json=mixed_wire_record())
    assert score.status_code == 404
    assert score.content == b'{"detail":"not found"}'


def test_dev_mode_shows_the_target_and_scores_without_storing(
        tmp_path) -> None:
    from pathlib import Path

    from pipeline.config import load_scoring_config
    from service.scoring import wire_for_close
    from pipeline.score import score_trial

    fixture, _ = _world(tmp_path)
    record = store.read_day_record(fixture["store"], DAY)
    dev_client = TestClient(create_app(fixture["service_config"],
                                       dev_mode=True))

    dev_view = dev_client.get("/api/dev").json()
    assert dev_view["target_id"] == record.target_id
    assert dev_view["trial_code"] == record.trial_code

    # The target and each pool image answer in dev mode.
    assert dev_client.get(f"/image/{record.target_id}").status_code == 200
    other = [image_id for image_id in fixture["image_ids"]
             if image_id != record.target_id][0]
    assert dev_client.get(f"/image/{other}").status_code == 200

    answer = dev_client.post("/api/dev/score", json=mixed_wire_record())
    assert answer.status_code == 200
    body = answer.json()
    assert len(body["rankings"]) == len(fixture["image_ids"])
    assert [row["position"] for row in body["rankings"]] \
        == list(range(1, len(fixture["image_ids"]) + 1))
    targets = [row for row in body["rankings"] if row["is_target"]]
    assert len(targets) == 1
    assert targets[0]["position"] == body["target_position"]

    # The dev numbers equal the production path on the same record.
    config = load_scoring_config(Path(fixture["scoring_config_path"]))
    wired = wire_for_close(config, fixture["scoring_config_path"],
                           fixture["data"], fixture["providers"])
    direct = score_trial(mixed_wire_record(), record.target_id,
                         wired.context, wired.encoders)
    assert body["trial"]["p"] == pytest.approx(direct.p, abs=1e-6)
    assert body["trial"]["decoy_count"] == direct.decoy_count

    # Nothing is stored and the day does not move.
    assert store.list_submissions(fixture["store"], DAY) == ()
    assert store.read_day_record(fixture["store"], DAY).status == "open"


def test_an_empty_store_answers_with_constants(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    client = TestClient(create_app(fixture["service_config"]))
    assert client.get("/api/day").status_code == 404
    assert client.get("/api/day").content \
        == b'{"detail":"no day open"}'
    assert client.post("/api/submission",
                       json=mixed_wire_record()).status_code == 404
