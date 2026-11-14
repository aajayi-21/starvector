"""The floor of the daily board (spec A2 section 9.5, decision D12).

A player shows on the public daily board of a day when the store holds
a submission of that player on 3 or more earlier days. The caller gets
the caller's own row below the floor. No trial score moves.
"""

import datetime
import json
from pathlib import Path

from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, build_service_fixture, mint_player,
                         mixed_wire_record, pinned_session_value,
                         plant_session)

from service import auth, rollup, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

FIRST = datetime.date(2026, 8, 12)
TOKEN = "test-operator-token"
CAST = ("ade", "bru", "cyd")


def test_the_pure_rule_keeps_public_rows_and_the_callers_own() -> None:
    rows = [{"player": "ade", "p": 0.9}, {"player": "bru", "p": 0.5},
            {"player": "cyd", "p": 0.1}]
    earlier = {"ade": 3, "bru": 2}
    assert rollup.DAILY_BOARD_FLOOR_DAYS == 3
    shown = rollup.public_board_rows(rows, earlier, "bru")
    assert [(row["player"], row["public"]) for row in shown] \
        == [("ade", True), ("bru", False)]
    # A caller at the floor sees public rows alone, and no row moves.
    shown = rollup.public_board_rows(rows, earlier, "ade")
    assert shown == [{"player": "ade", "p": 0.9, "public": True}]
    assert rows[0] == {"player": "ade", "p": 0.9}


def _play_day(config, root: Path, day: str, names: tuple[str, ...]) -> None:
    open_day(config, date=day, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    for index, name in enumerate(names):
        store.write_once_json(
            store.submission_path(root, day, name),
            {"day": day, "player": name, "trial_id": f"{index}" * 32,
             "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)


def _world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    root = Path(config.store_root)
    tokens = {}
    for name in CAST:
        _record, tokens[name] = mint_player(
            config, player=name, display_name=name.title(),
            clock=lambda: FIXED_CLOCK)
        plant_session(root, tokens[name])
    # ade plays each day, bru misses the first, cyd plays the last alone.
    days = [(FIRST + datetime.timedelta(days=n)).isoformat()
            for n in range(4)]
    _play_day(config, root, days[0], ("ade",))
    _play_day(config, root, days[1], ("ade", "bru"))
    _play_day(config, root, days[2], ("ade", "bru"))
    _play_day(config, root, days[3], CAST)
    client = TestClient(create_app(config, operator_token=TOKEN),
                        base_url="https://testserver")
    return root, client, tokens, days


def _board(client, token, day):
    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(token))
    return client.get(f"/api/leaderboard?day={day}").json()


def test_a_player_shows_after_three_earlier_played_days(tmp_path) -> None:
    _root, client, tokens, days = _world(tmp_path)
    last = days[3]
    # On the fourth day ade has 3 earlier days, bru has 2, cyd has 0.
    seen_by_ade = _board(client, tokens["ade"], last)
    assert [(row["player"], row["public"]) for row in seen_by_ade["rows"]] \
        == [("ade", True)]
    assert seen_by_ade["floor"] == {"played_days": 3,
                                    "caller_played_days": 3}
    seen_by_bru = _board(client, tokens["bru"], last)
    assert {row["player"]: row["public"] for row in seen_by_bru["rows"]} \
        == {"ade": True, "bru": False}
    assert seen_by_bru["floor"]["caller_played_days"] == 2
    seen_by_cyd = _board(client, tokens["cyd"], last)
    assert {row["player"]: row["public"] for row in seen_by_cyd["rows"]} \
        == {"ade": True, "cyd": False}
    # An earlier board has its own count: on the third day nobody is
    # at the floor, and each caller sees the caller's own row alone.
    third = _board(client, tokens["bru"], days[2])
    assert [(row["player"], row["public"]) for row in third["rows"]] \
        == [("bru", False)]


def test_the_floor_moves_no_trial_score(tmp_path, monkeypatch) -> None:
    root, client, tokens, days = _world(tmp_path)
    last = days[3]
    stored = {name: json.loads(store.trial_row_path(
        root, last, name).read_text()) for name in CAST}
    with_floor = {row["player"]: row
                  for name in CAST
                  for row in _board(client, tokens[name], last)["rows"]}
    monkeypatch.setattr(rollup, "DAILY_BOARD_FLOOR_DAYS", 0)
    without = {row["player"]: row
               for row in _board(client, tokens["ade"], last)["rows"]}
    assert set(without) == set(CAST)
    for name in CAST:
        for field in ("p", "target_rank", "decoy_count"):
            assert with_floor[name][field] == without[name][field]
        assert without[name]["p"] == stored[name]["p"]
    # The stored trial rows are byte-equal after each board read.
    assert {name: json.loads(store.trial_row_path(
        root, last, name).read_text()) for name in CAST} == stored
