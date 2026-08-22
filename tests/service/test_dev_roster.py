"""Integration: the console roster and history (spec A1 item A6).

The roster, the player history, and the player growth on the
dev submission and rankings reads. Each sits behind the standing
dev gate and answers the constant 404 in the other conditions.
"""

from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import players, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

FIRST_DAY = "2026-08-10"
OPEN_DAY = "2026-08-12"
OPERATOR_TOKEN = "test-operator-token"
HEADERS = {"Authorization": f"Bearer {OPERATOR_TOKEN}"}


def _send(fixture, day: str, player: str) -> None:
    store.write_once_json(
        store.submission_path(fixture["store"], day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})


def _world(tmp_path, *, dev_mode=True, minted=True):
    """One revealed day bru played, one open day ade played."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    if minted:
        for name, label, secret in (("ade", "Ade", "1" * 43),
                                    ("bru", "Bru Lin", "2" * 43)):
            players.mint_player(config, player=name, display_name=label,
                                clock=lambda: FIXED_CLOCK, secret=secret)
    open_day(config, date=FIRST_DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    _send(fixture, FIRST_DAY, "bru")
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    open_day(config, date=OPEN_DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="c" * 32, secret="d" * 64)
    _send(fixture, OPEN_DAY, "ade")
    app = create_app(config, dev_mode=dev_mode,
                     operator_token=OPERATOR_TOKEN if minted else None)
    return fixture, TestClient(app)


def test_the_two_reads_answer_the_constant_without_the_gate(
        tmp_path) -> None:
    _fixture, dev_client = _world(tmp_path)
    _off, off_client = _world(tmp_path / "off", dev_mode=False)
    for path in ("/api/dev/players", "/api/dev/history"):
        refused = dev_client.get(path)
        absent = off_client.get(path, headers=HEADERS)
        assert refused.status_code == absent.status_code == 404
        assert refused.content == absent.content


def test_the_roster_serves_each_stored_player(tmp_path) -> None:
    _fixture, client = _world(tmp_path)
    body = client.get("/api/dev/players", headers=HEADERS).json()
    rows = body["players"]
    assert [row["player"] for row in rows] == ["ade", "bru"]
    for row in rows:
        assert set(row) == {"player", "display_name", "status",
                            "created_at"}
    assert rows[1]["display_name"] == "Bru Lin"
    assert {row["status"] for row in rows} == {"active"}


def test_the_roster_holds_the_configured_player_with_no_record(
        tmp_path) -> None:
    _fixture, client = _world(tmp_path, minted=False)
    rows = client.get("/api/dev/players",
                      headers=HEADERS).json()["players"]
    assert rows == [{"player": "ade", "display_name": "ade",
                     "status": "configured", "created_at": None}]


def test_the_history_serves_each_stored_day_newest_first(
        tmp_path) -> None:
    fixture, client = _world(tmp_path)
    body = client.get("/api/dev/history?player=bru",
                      headers=HEADERS).json()
    assert body["player"] == "bru"
    days = body["days"]
    assert [row["day"] for row in days] == [OPEN_DAY, FIRST_DAY]
    open_row, revealed_row = days
    assert open_row["status"] == "open"
    assert open_row["submitted"] is False
    assert open_row["trial"] is None
    assert revealed_row["status"] == "revealed"
    assert revealed_row["submitted"] is True
    stored = store.read_json_or_none(store.trial_row_path(
        fixture["store"], FIRST_DAY, "bru"))
    assert revealed_row["trial"] == {
        "p": stored["p"], "target_rank": stored["target_rank"],
        "decoy_count": stored["decoy_count"],
        "beaten": stored["beaten"], "tied": stored["tied"]}
    for row in days:
        assert set(row) == {"day", "status", "trial_code", "target_id",
                            "submitted", "trial"}


def test_the_history_defaults_to_the_configured_player(
        tmp_path) -> None:
    _fixture, client = _world(tmp_path)
    body = client.get("/api/dev/history", headers=HEADERS).json()
    assert body["player"] == "ade"
    open_row = body["days"][0]
    assert open_row["submitted"] is True


def test_the_history_refuses_an_illegal_name(tmp_path) -> None:
    _fixture, client = _world(tmp_path)
    answer = client.get("/api/dev/history?player=A%20Player",
                        headers=HEADERS)
    assert answer.status_code == 400
    assert answer.json()["cause"] == "bad-player"


def test_the_submission_read_grows_the_player_parameter(
        tmp_path) -> None:
    _fixture, client = _world(tmp_path)
    theirs = client.get(
        f"/api/dev/submission?day={FIRST_DAY}&player=bru",
        headers=HEADERS)
    assert theirs.status_code == 200
    assert theirs.json()["player"] == "bru"
    # No parameter names the configured player - today's caller
    # sees today's behavior.
    mine = client.get(f"/api/dev/submission?day={OPEN_DAY}",
                      headers=HEADERS)
    assert mine.status_code == 200
    assert mine.json()["player"] == "ade"
    bad = client.get(f"/api/dev/submission?day={OPEN_DAY}&player=..",
                     headers=HEADERS)
    assert bad.status_code == 400
    assert bad.json()["cause"] == "bad-player"


def test_the_rankings_read_grows_the_player_parameter(
        tmp_path) -> None:
    fixture, client = _world(tmp_path)
    answer = client.get(
        f"/api/dev/rankings?day={FIRST_DAY}&player=bru",
        headers=HEADERS)
    assert answer.status_code == 200
    stored = store.read_json_or_none(store.trial_row_path(
        fixture["store"], FIRST_DAY, "bru"))
    # The resident context rescores the stored record, thus the
    # trial agrees with the stored row.
    assert answer.json()["trial"]["p"] == stored["p"]
