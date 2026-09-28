"""Integration: the operator console's paths (spec BR1 section 7).

The day view, the automatic days, the players with their devices,
and the results database. Each path sits behind the dev gate and
answers the constant 404 without --dev or with a bearer that does not
agree.
"""

import dataclasses
import datetime
import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import access, auth, index, players, rollover, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

FIRST_DAY = "2026-08-10"
OPEN_DAY = "2026-08-12"
TOKEN = "test-operator-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
HOUR = "22:00"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 24

# Each new console path with its method.
_PATHS = (
    ("GET", f"/api/dev/day?day={OPEN_DAY}"),
    ("GET", "/api/dev/schedule"),
    ("POST", "/api/dev/rollover/pause"),
    ("POST", "/api/dev/rollover/run"),
    ("GET", "/api/dev/players/ade"),
    ("GET", "/api/dev/players/ade/avatar"),
    ("POST", "/api/dev/players/ade/rotate"),
    ("POST", "/api/dev/players/ade/revoke"),
    ("POST", "/api/dev/players/ade/restore"),
    ("POST", "/api/dev/players/ade/signout"),
    ("POST", "/api/dev/players/ade/device-code"),
    ("DELETE", "/api/dev/players/ade/sessions/" + "a" * 64),
    ("POST", "/api/dev/prune"),
    ("GET", "/api/dev/index"),
    ("POST", "/api/dev/index/build"),
    ("POST", "/api/dev/index/verify"),
    ("POST", "/api/dev/index/query"),
)


class _Clock:
    """A settable instant for the server and the day commands."""

    def __init__(self, text: str) -> None:
        self.instant = datetime.datetime.fromisoformat(text).replace(
            tzinfo=datetime.UTC)

    def __call__(self) -> datetime.datetime:
        return self.instant


def _send(fixture, day: str, player: str) -> None:
    store.write_once_json(
        store.submission_path(fixture["store"], day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})


def _world(tmp_path, monkeypatch, *, dev_mode=True, hour=None,
           instant="2026-08-12T12:00:00"):
    """One revealed day bru played, one open day ade played, two
    players, and a pinned clock."""
    from service import day as day_module
    from service import server as server_module

    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc=hour)
    clock = _Clock(instant)
    monkeypatch.setattr(day_module, "utc_now", clock)
    monkeypatch.setattr(server_module, "utc_now", clock)
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
    client = TestClient(create_app(config, dev_mode=dev_mode,
                                   operator_token=TOKEN))
    return fixture, config, client, clock


def _call(client, method: str, path: str, headers=None, body=None):
    return client.request(method, path, headers=headers or {},
                          json=body)


def test_each_path_answers_the_constant_without_the_gate(
        tmp_path, monkeypatch) -> None:
    _fixture, _config, dev_client, _clock = _world(tmp_path, monkeypatch)
    _off, _config_off, off_client, _clock_off = _world(
        tmp_path / "off", monkeypatch, dev_mode=False)
    constant = off_client.get("/api/dev/days", headers=HEADERS)
    assert constant.status_code == 404
    for method, path in _PATHS:
        for client, headers in ((off_client, HEADERS), (dev_client, {}),
                                (dev_client,
                                 {"Authorization": "Bearer nope"})):
            answer = _call(client, method, path, headers, {})
            assert answer.status_code == 404, (method, path)
            assert answer.content == constant.content, (method, path)


def test_the_day_detail_names_each_send(tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    revealed = client.get(f"/api/dev/day?day={FIRST_DAY}",
                          headers=HEADERS).json()
    assert revealed["status"] == "revealed"
    assert revealed["closes_at"] is None
    assert revealed["credit"] is None
    assert [row["player"] for row in revealed["sends"]] == ["bru"]
    send = revealed["sends"][0]
    assert send["display_name"] == "Bru Lin"
    stored = store.read_json_or_none(store.trial_row_path(
        fixture["store"], FIRST_DAY, "bru"))
    assert send["trial"]["p"] == stored["p"]
    assert send["trial"]["target_rank"] == stored["target_rank"]

    live = client.get(f"/api/dev/day?day={OPEN_DAY}", headers=HEADERS).json()
    assert live["status"] == "open"
    assert [row["player"] for row in live["sends"]] == ["ade"]
    assert live["sends"][0]["trial"] is None
    assert "secret" not in live and "pick_seed" not in live

    days = client.get("/api/dev/days", headers=HEADERS).json()["days"]
    assert [row["sends"] for row in days] == [1, 1]

    missing = client.get("/api/dev/day?day=2026-01-01", headers=HEADERS)
    assert missing.status_code == 404


def test_the_schedule_is_off_with_no_hour(tmp_path, monkeypatch) -> None:
    _fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    view = client.get("/api/dev/schedule", headers=HEADERS).json()
    assert view["closes_at_utc"] is None
    assert view["due_now"] is None and view["next_run"] is None
    assert view["latest"] == {"day": OPEN_DAY, "status": "open",
                              "closes_at": None}
    assert view["paused"] is False and view["runs"] == []
    refused = client.post("/api/dev/rollover/run", headers=HEADERS)
    assert refused.status_code == 409
    assert refused.json()["cause"] == "no-schedule"


def test_the_schedule_names_the_next_run(tmp_path, monkeypatch) -> None:
    _fixture, _config, client, _clock = _world(
        tmp_path, monkeypatch, hour=HOUR, instant="2026-08-12T12:00:00")
    view = client.get("/api/dev/schedule", headers=HEADERS).json()
    assert view["latest"]["closes_at"] == "2026-08-12T22:00:00+00:00"
    assert view["due_now"]["steps"] == []
    assert view["next_run"] == {"at": "2026-08-12T22:00:00+00:00",
                                "steps": ["close", "reveal", "open"],
                                "opens": "2026-08-13"}
    assert view["lock_held"] is False


def test_the_pause_is_stored_and_checked(tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch,
                                              hour=HOUR)
    view = client.post("/api/dev/rollover/pause", headers=HEADERS,
                       json={"paused": True, "note": "holiday"}).json()
    assert view["paused"] is True and view["pause_note"] == "holiday"
    assert store.read_rollover_control(fixture["store"]).paused is True
    for body in ({"paused": "yes"}, {"paused": True, "note": "x" * 201},
                 {"paused": True, "note": "two\nlines"}):
        refused = client.post("/api/dev/rollover/pause", headers=HEADERS,
                              json=body)
        assert refused.status_code == 400
    view = client.post("/api/dev/rollover/pause", headers=HEADERS,
                       json={"paused": False}).json()
    assert view["paused"] is False and view["pause_note"] == ""


def test_do_what_is_due_moves_a_due_day(tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(
        tmp_path, monkeypatch, hour=HOUR, instant="2026-08-12T22:30:00")
    # The pause stops the timer, and not the operator's button.
    client.post("/api/dev/rollover/pause", headers=HEADERS,
                json={"paused": True})
    answer = client.post("/api/dev/rollover/run", headers=HEADERS).json()
    assert answer["run"]["outcome"] == "moved"
    assert answer["run"]["steps"] == ["close", "reveal", "open"]
    assert answer["run"]["source"] == "console"
    assert store.read_day_record(fixture["store"],
                                 OPEN_DAY).status == "revealed"
    assert store.latest_day(fixture["store"]) == "2026-08-13"
    runs = answer["schedule"]["runs"]
    assert [run["outcome"] for run in runs] == ["moved"]

    again = client.post("/api/dev/rollover/run", headers=HEADERS).json()
    assert again["run"]["outcome"] == "nothing due"
    assert again["run"]["steps"] == []


def test_do_what_is_due_refuses_while_a_rollover_holds_the_lock(
        tmp_path, monkeypatch) -> None:
    import os

    fixture, _config, client, _clock = _world(
        tmp_path, monkeypatch, hour=HOUR, instant="2026-08-12T22:30:00")
    handle = rollover.hold_lock(store.rollover_lock_path(fixture["store"]))
    try:
        view = client.get("/api/dev/schedule", headers=HEADERS).json()
        assert view["lock_held"] is True
        refused = client.post("/api/dev/rollover/run", headers=HEADERS)
        assert refused.status_code == 409
        assert refused.json()["cause"] == "locked"
    finally:
        os.close(handle)
    assert store.read_day_record(fixture["store"], OPEN_DAY).status == "open"


def test_a_failing_step_is_recorded_with_the_steps_before_it(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, clock = _world(
        tmp_path, monkeypatch, hour=HOUR, instant="2026-08-12T22:30:00")

    def post(path: str, _timeout: float) -> rollover.Answer:
        if path.endswith("/reveal"):
            return rollover.Answer(status=500, body={"detail": "boom"})
        answer = client.post(path, headers=HEADERS)
        return rollover.Answer(status=answer.status_code,
                               body=answer.json())

    run = rollover.run_and_record(
        root=fixture["store"], closes_at_utc=HOUR, post=post, now=clock,
        source="command-line", retries=0, sleep=lambda _: None,
        say=lambda _line: None)
    assert run.outcome == "failed"
    assert run.steps == ("close",)
    assert "boom" in run.detail
    assert store.list_rollover_runs(fixture["store"], 5) == (run,)


def test_the_player_detail_holds_no_secret(tmp_path, monkeypatch) -> None:
    fixture, _config, client, clock = _world(tmp_path, monkeypatch)
    access.open_session(fixture["store"], "ade", user_agent="Playwright",
                        instant=clock.instant)
    detail = client.get("/api/dev/players/ade", headers=HEADERS).json()
    assert detail["display_name"] == "Ade"
    assert detail["sends"] == 1
    assert detail["has_avatar"] is False
    assert len(detail["sessions"]) == 1
    assert "token_hash" not in detail
    text = client.get("/api/dev/players/ade", headers=HEADERS).text
    record = store.read_player_record(fixture["store"], "ade")
    assert record.token_hash not in text

    rows = client.get("/api/dev/players", headers=HEADERS).json()["players"]
    ade = next(row for row in rows if row["player"] == "ade")
    assert ade["devices"] == 1 and ade["sends"] == 1
    assert ade["last_signed_in"] == detail["sessions"][0]["created_at"]

    assert client.get("/api/dev/players/nobody",
                      headers=HEADERS).status_code == 404
    assert client.get("/api/dev/players/Not%20A%20Name",
                      headers=HEADERS).status_code == 400


def test_the_avatar_reads_with_the_bearer(tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    assert client.get("/api/dev/players/ade/avatar",
                      headers=HEADERS).status_code == 404
    store.set_account_avatar(fixture["store"], "ade", PNG,
                             timestamp=FIXED_CLOCK)
    served = client.get("/api/dev/players/ade/avatar", headers=HEADERS)
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"
    assert client.get("/api/dev/players/ade",
                      headers=HEADERS).json()["has_avatar"] is True


def test_devices_sign_out_one_at_a_time_or_all(tmp_path,
                                               monkeypatch) -> None:
    fixture, _config, client, clock = _world(tmp_path, monkeypatch)
    for _ in range(3):
        access.open_session(fixture["store"], "ade", user_agent="Firefox",
                            instant=clock.instant)
    sessions = client.get("/api/dev/players/ade",
                          headers=HEADERS).json()["sessions"]
    ended = client.delete(f"/api/dev/players/ade/sessions/{sessions[0]['id']}",
                          headers=HEADERS)
    assert ended.json() == {"player": "ade", "ended": 1}
    assert client.delete(
        f"/api/dev/players/ade/sessions/{sessions[0]['id']}",
        headers=HEADERS).status_code == 404
    assert client.delete("/api/dev/players/ade/sessions/not-a-digest",
                         headers=HEADERS).status_code == 404
    everything = client.post("/api/dev/players/ade/signout",
                             headers=HEADERS).json()
    assert everything == {"player": "ade", "ended": 2}
    assert store.list_sessions(fixture["store"], "ade") == ()


def test_a_new_invite_keeps_the_sessions(tmp_path, monkeypatch) -> None:
    fixture, _config, client, clock = _world(tmp_path, monkeypatch)
    value = access.open_session(fixture["store"], "ade",
                                user_agent="Firefox", instant=clock.instant)
    turned = client.post("/api/dev/players/ade/rotate",
                         headers=HEADERS).json()
    assert turned["join_path"] == f"/join/{turned['token']}"
    assert turned["token"].startswith("ade.")
    # The earlier invite stops, and the session does not.
    assert client.get(f"/join/ade.{'1' * 43}",
                      follow_redirects=False).status_code == 401
    assert access.resolve_session(fixture["store"], value,
                                  clock.instant) == "ade"
    joined = client.get(turned["join_path"], follow_redirects=False)
    assert joined.status_code == 302


def test_revoke_and_restore_move_the_access(tmp_path, monkeypatch) -> None:
    fixture, _config, client, clock = _world(tmp_path, monkeypatch)
    access.open_session(fixture["store"], "bru", user_agent="Firefox",
                        instant=clock.instant)
    revoked = client.post("/api/dev/players/bru/revoke",
                          headers=HEADERS).json()
    assert revoked == {"player": "bru", "status": "revoked"}
    assert store.list_sessions(fixture["store"], "bru") == ()
    again = client.post("/api/dev/players/bru/revoke", headers=HEADERS)
    assert again.status_code == 409
    code = client.post("/api/dev/players/bru/device-code", headers=HEADERS)
    assert code.status_code == 409
    restored = client.post("/api/dev/players/bru/restore",
                           headers=HEADERS).json()
    assert restored["join_path"].startswith("/join/bru.")
    assert store.read_player_record(fixture["store"],
                                    "bru").status == "active"


def test_a_console_device_code_signs_a_device_in(tmp_path,
                                                 monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    issued = client.post("/api/dev/players/ade/device-code",
                         headers=HEADERS).json()
    assert len(issued["code"]) == 8
    assert issued["display"] == f"{issued['code'][:4]}-{issued['code'][4:]}"
    detail = client.get("/api/dev/players/ade", headers=HEADERS).json()
    assert len(detail["device_codes"]) == 1
    assert issued["code"] not in client.get("/api/dev/players/ade",
                                            headers=HEADERS).text
    phone = TestClient(client.app)
    redeemed = phone.post("/api/device-code/redeem",
                          json={"code": issued["display"]})
    assert redeemed.status_code == 200
    # The cookie is Secure and the test client speaks http, thus the
    # session is read from the answer and not sent back.
    value = redeemed.cookies.get(auth.SESSION_COOKIE)
    assert access.resolve_session(fixture["store"], value,
                                  _clock.instant) == "ade"


def test_the_prune_removes_what_expired(tmp_path, monkeypatch) -> None:
    fixture, _config, client, clock = _world(tmp_path, monkeypatch)
    old = clock.instant - datetime.timedelta(days=400)
    access.open_session(fixture["store"], "ade", user_agent="Firefox",
                        instant=old)
    access.issue_device_code(fixture["store"], "ade", old)
    access.open_session(fixture["store"], "ade", user_agent="Firefox",
                        instant=clock.instant)
    counts = client.post("/api/dev/prune", headers=HEADERS).json()
    assert counts == {"sessions": 1, "device_codes": 1}
    assert len(store.list_sessions(fixture["store"], "ade")) == 1


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_index_builds_checks_and_describes(tmp_path,
                                               monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    before = client.get("/api/dev/index", headers=HEADERS).json()
    assert before["exists"] is False and before["tables"] == []
    built = client.post("/api/dev/index/build", headers=HEADERS).json()
    assert built["exists"] is True and built["current"] is True
    counts = {table["name"]: table["rows"] for table in built["tables"]}
    assert counts["players"] == 2
    assert counts["days"] == 2
    assert counts["submissions"] == 2
    # I7: the open day's send is in, and no trial row of it.
    assert counts["trials"] == 1
    assert counts["revealed_trials"] == 1
    trials = next(table for table in built["tables"]
                  if table["name"] == "trials")
    assert "p" in trials["columns"]
    checked = client.post("/api/dev/index/verify", headers=HEADERS).json()
    assert checked == {"agrees": True, "problems": []}

    _send(fixture, OPEN_DAY, "bru")
    stale = client.get("/api/dev/index", headers=HEADERS).json()
    assert stale["current"] is False


def test_the_query_reads_and_refuses_each_write(tmp_path,
                                                monkeypatch) -> None:
    fixture, config, client, _clock = _world(tmp_path, monkeypatch)
    answer = client.post("/api/dev/index/query", headers=HEADERS, json={
        "sql": "SELECT player, p FROM revealed_trials ORDER BY player"})
    assert answer.status_code == 200
    body = answer.json()
    assert body["columns"] == ["player", "p"]
    assert [row[0] for row in body["rows"]] == ["bru"]
    assert body["truncated"] is False

    target = index.index_path(Path(config.data_root))
    kept = _digest(target)
    for sql in ("DELETE FROM trials",
                "INSERT INTO players VALUES ('x', 'x', 'active', 'now')",
                "UPDATE days SET status = 'open'",
                "DROP TABLE trials",
                "CREATE TABLE extra (a)",
                "ATTACH DATABASE 'other.sqlite' AS other",
                "PRAGMA query_only = OFF",
                "SELECT 1; DELETE FROM trials",
                "SELECT load_extension('x')",
                "",
                "SELECT '" + "x" * index.QUERY_TEXT_CAP + "'"):
        refused = client.post("/api/dev/index/query", headers=HEADERS,
                              json={"sql": sql})
        assert refused.status_code == 400, sql
        assert refused.json()["cause"] == "bad-query", sql
    assert _digest(target) == kept
    assert client.post("/api/dev/index/query", headers=HEADERS,
                       json={"sql": 3}).status_code == 400


def test_the_query_caps_rows_and_time(tmp_path, monkeypatch) -> None:
    _fixture, config, client, _clock = _world(tmp_path, monkeypatch)
    client.post("/api/dev/index/build", headers=HEADERS)
    target = index.index_path(Path(config.data_root))
    counted = index.read_only_query(
        target, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 "
                "FROM n WHERE i < 50) SELECT i FROM n", row_cap=10)
    assert len(counted["rows"]) == 10 and counted["truncated"] is True
    with pytest.raises(index.ResultsIndexError, match="stopped"):
        index.read_only_query(
            target, "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT "
                    "i + 1 FROM n) SELECT COUNT(*) FROM n", seconds=0.2)
    with pytest.raises(index.ResultsIndexError):
        index.read_only_query(target, "SELECT zeroblob(20000000)")


def test_a_refused_write_names_the_read_only_rule(tmp_path,
                                                 monkeypatch) -> None:
    _fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    refused = client.post("/api/dev/index/query", headers=HEADERS,
                          json={"sql": "DELETE FROM trials"})
    assert refused.json()["detail"].startswith("read-only:")
