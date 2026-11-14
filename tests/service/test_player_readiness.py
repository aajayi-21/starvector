"""Spec PL1: the limits, the stale tab, the hardening, and the export.

Offline, on the fake-provider world. Each test names the section of
docs/specs/player-readiness.md that it holds.
"""

import asyncio
import datetime
import json
import logging
import os
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from svc_fixture import mint_player
from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from pipeline.config import load_scoring_config, parse_scoring_config
from service import index, limits, players, rollover, scoring, store
from service.config import ServiceConfig
from service.day import close_day, open_day, rescore_days, reveal_day
from service.server import create_app

DAY = "2026-08-12"
NEXT_DAY = "2026-08-13"
TOKEN = "test-operator-token"
BEARER = {"Authorization": f"Bearer {TOKEN}"}
REPO = Path(__file__).resolve().parents[2]


def _clock() -> str:
    return FIXED_CLOCK


def _world(tmp_path, **keywords):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=_clock, pick_seed="a" * 32,
             secret="b" * 64)
    return fixture, config, TestClient(create_app(config, **keywords))


def _played_world(tmp_path):
    """One revealed day, with one send, and the app."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=_clock, pick_seed="a" * 32,
             secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "e" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, providers=fixture["providers"], clock=_clock)
    reveal_day(config, clock=_clock)
    return fixture, config


# -- section 1: the limits ----------------------------------------------


def test_a_declared_body_above_the_cap_refuses_before_the_read(
        tmp_path) -> None:
    fixture, _config, client = _world(tmp_path)
    answer = client.post(
        f"/api/submission?day={DAY}",
        content=b"x" * (limits.BODY_BYTE_CAP + 1),
        headers={"content-type": "application/json"})
    assert answer.status_code == 413
    assert answer.json() == {"cause": "body-too-large"}
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_a_chunked_body_above_the_cap_refuses(tmp_path) -> None:
    """No declared length: the stream count is the guard."""
    _fixture, _config, client = _world(tmp_path)

    def chunks():
        for _ in range(3):
            yield b"x" * (limits.BODY_BYTE_CAP // 2)

    answer = client.post(f"/api/submission?day={DAY}", content=chunks())
    assert answer.status_code == 413


def test_the_body_cap_reads_nothing_on_the_avatar_path(tmp_path) -> None:
    """The avatar keeps its own check, its own cap, and its refusal."""
    _fixture, _config, client = _world(tmp_path)
    answer = client.put("/api/account/avatar",
                        content=b"x" * (store.AVATAR_BYTE_CAP + 1))
    assert answer.status_code == 400
    assert answer.json()["cause"] == "bad-avatar"


def test_the_body_cap_gives_the_app_each_byte(tmp_path) -> None:
    """A body below the cap gets to the handler in full."""
    fixture, _config, client = _world(tmp_path)
    ack = client.post(f"/api/submission?day={DAY}", json=mixed_wire_record())
    assert ack.status_code == 200
    stored = store.read_json_or_none(
        store.submission_path(fixture["store"], DAY, "ade"))
    assert stored["record"] == mixed_wire_record()


def test_a_slow_body_stops_at_the_deadline() -> None:
    sent = []

    async def never_ends():
        await asyncio.sleep(10)

    async def send(message):
        sent.append(message)

    async def app(_scope, _receive, _send):
        raise AssertionError("the app must not run")

    guard = limits.BodyCap(app, seconds=0.01)
    asyncio.run(guard({"type": "http", "path": "/api/x", "headers": []},
                      never_ends, send))
    assert sent[0]["status"] == 408


@pytest.mark.parametrize("record, refused", [
    ({"canvas_strokes": [{"points": [[0, 0]]}] * 3}, True),
    ({"canvas_strokes": [{"points": [[0, 0]] * 2}] * 2}, False),
    ({"canvas_strokes": [{"points": [[0, 0]] * 5}]}, True),
    # A bad shape is the refusal of Layer 0 and not of this check.
    ({"canvas_strokes": "no"}, False),
    ({"canvas_strokes": [7]}, False),
    ("no", False),
])
def test_the_record_caps(record, refused) -> None:
    answer = limits.record_caps_refusal(record, stroke_cap=2, point_cap=4)
    assert (answer is not None) == refused


def test_a_record_above_the_caps_refuses_at_the_server(tmp_path) -> None:
    fixture, _config, client = _world(tmp_path)
    record = mixed_wire_record()
    stroke = {"points": [[0.1, 0.1], [0.2, 0.2]], "group_id": None}
    record["canvas_strokes"] = [stroke] * (limits.STROKE_CAP + 1)
    answer = client.post(f"/api/submission?day={DAY}", json=record)
    assert answer.status_code == 400
    assert answer.json()["cause"] == "too-much-drawing"
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_the_caps_do_not_guard_a_stored_record(tmp_path) -> None:
    """A close reads stored records with Layer 0 alone (I4): a stored
    record above a cap scores."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=_clock, pick_seed="a" * 32,
             secret="b" * 64)
    record = mixed_wire_record()
    point = [[0.1 + 0.8 * (at % 2), 0.5] for at in range(limits.POINT_CAP + 1)]
    record["canvas_strokes"].append({"points": point, "group_id": None})
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "e" * 32,
         "received_at": FIXED_CLOCK, "record": record})
    assert close_day(config, providers=fixture["providers"],
                     clock=_clock) == 1


def test_layer_zero_runs_off_the_loop_thread(tmp_path, monkeypatch) -> None:
    import threading

    from service import server as server_module

    seen = []
    original = server_module.validate_submission

    def noting(*arguments):
        seen.append(threading.current_thread())
        return original(*arguments)

    monkeypatch.setattr(server_module, "validate_submission", noting)
    _fixture, _config, client = _world(tmp_path)
    loop_thread = []

    @client.app.get("/loop-thread")
    async def loop_thread_view():
        loop_thread.append(threading.current_thread())
        return {}

    client.get("/loop-thread")
    assert client.post(f"/api/submission?day={DAY}",
                       json=mixed_wire_record()).status_code == 200
    assert seen and seen[0] is not loop_thread[0]


def test_practice_stops_at_the_player_cap(tmp_path) -> None:
    fixture, config = _played_world(tmp_path)
    limiter = limits.WindowLimiter(window_seconds=60, client_cap=2,
                                   global_cap=100)
    client = TestClient(create_app(config, practice_limiter=limiter))
    body = {"day": DAY, "record": mixed_wire_record()}
    assert client.post("/api/practice/score", json=body).status_code == 200
    assert client.post("/api/practice/score", json=body).status_code == 200
    third = client.post("/api/practice/score", json=body)
    assert third.status_code == 429
    assert third.json() == {"cause": "practice-limit"}


def test_a_practice_refused_by_layer_zero_does_not_count(tmp_path) -> None:
    fixture, config = _played_world(tmp_path)
    limiter = limits.WindowLimiter(window_seconds=60, client_cap=1,
                                   global_cap=100)
    client = TestClient(create_app(config, practice_limiter=limiter))
    empty = {"impressions": [], "canvas_strokes": [], "groups": [],
             "relations": [], "pasted_text": None}
    for _ in range(3):
        answer = client.post("/api/practice/score",
                             json={"day": DAY, "record": empty})
        assert answer.status_code == 400
    assert client.post("/api/practice/score",
                       json={"day": DAY, "record": mixed_wire_record()
                             }).status_code == 200


def test_the_practice_limit_has_a_process_cap_too() -> None:
    now = [0.0]
    limiter = limits.WindowLimiter(window_seconds=60, client_cap=5,
                                   global_cap=2, clock=lambda: now[0])
    limiter.record("a")
    limiter.record("b")
    assert not limiter.allowed("c")
    now[0] = 61.0
    assert limiter.allowed("c")


def test_the_practice_values_are_the_spec_values() -> None:
    limiter = limits.practice_limiter()
    assert limiter.window_seconds == 3600
    assert limiter.client_cap == 30
    assert limiter.global_cap == 600


# -- section 2: the stale tab -------------------------------------------


def test_a_send_with_no_day_refuses(tmp_path) -> None:
    fixture, _config, client = _world(tmp_path)
    answer = client.post("/api/submission", json=mixed_wire_record())
    assert answer.status_code == 400
    assert answer.json()["cause"] == "day-required"
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_the_stale_tab_gets_409_and_spends_no_send(tmp_path) -> None:
    """Yesterday's tab: the send names yesterday and today is open."""
    fixture, config = _played_world(tmp_path)
    open_day(config, date=NEXT_DAY, clock=_clock, pick_seed="c" * 32,
             secret="d" * 64)
    client = TestClient(create_app(config))
    stale = client.post(f"/api/submission?day={DAY}",
                        json=mixed_wire_record())
    assert stale.status_code == 409
    assert stale.json() == {"cause": "day-moved", "day": NEXT_DAY}
    # Today's only send is untouched.
    assert store.list_submissions(fixture["store"], NEXT_DAY) == ()
    assert client.get("/api/day").json()["submitted"] is False
    fresh = client.post(f"/api/submission?day={NEXT_DAY}",
                        json=mixed_wire_record())
    assert fresh.status_code == 200


def test_a_day_name_that_is_not_a_label_is_only_a_mismatch(tmp_path) -> None:
    """The name is compared and does not enter a path."""
    fixture, _config, client = _world(tmp_path)
    answer = client.post("/api/submission?day=../../etc",
                         json=mixed_wire_record())
    assert answer.status_code == 409
    assert answer.json()["cause"] == "day-moved"
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_the_ack_names_the_day_and_the_stored_bytes_do_not_move(
        tmp_path) -> None:
    fixture, _config, client = _world(tmp_path)
    ack = client.post(f"/api/submission?day={DAY}",
                      json=mixed_wire_record()).json()
    assert ack["day"] == DAY
    assert set(ack) == {"trial_id", "day", "atom_count"}
    stored = store.read_json_or_none(
        store.submission_path(fixture["store"], DAY, "ade"))
    assert set(stored) == {"day", "player", "trial_id", "received_at",
                           "record"}
    assert stored["record"] == mixed_wire_record()


def test_a_closing_day_with_its_own_name_still_says_closed(tmp_path) -> None:
    fixture, _config, client = _world(tmp_path)
    store.update_day_status(fixture["store"], DAY, expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)
    answer = client.post(f"/api/submission?day={DAY}",
                         json=mixed_wire_record())
    assert (answer.status_code, answer.json()) \
        == (409, {"cause": "day-closed"})


def test_the_day_view_and_practice_carry_the_stroke_floor(tmp_path) -> None:
    fixture, config = _played_world(tmp_path)
    client = TestClient(create_app(config))
    assert client.get("/api/day").json()["min_strokes"] == 2
    assert client.get("/api/practice").json()["min_strokes"] == 2


# -- section 3: close resilience ----------------------------------------


def _rollover_at(fixture, source: str, hour: str = "22:00"):
    instant = datetime.datetime(2026, 8, 12, 10, 0, tzinfo=datetime.UTC)
    return rollover.run_and_record(
        root=fixture["store"], closes_at_utc=hour,
        post=lambda _path, _timeout: rollover.Answer(200, {}),
        now=lambda: instant, source=source, say=lambda _line: None,
        retries=0, backoff_seconds=0.0, sleep=lambda _seconds: None)


def test_a_timer_firing_with_nothing_due_writes_no_run(tmp_path) -> None:
    fixture, _config, _client = _world(tmp_path)
    run = _rollover_at(fixture, "timer")
    assert run.outcome == "nothing due"
    assert store.list_rollover_runs(fixture["store"], 10) == ()


def test_a_console_run_with_nothing_due_writes_its_record(tmp_path) -> None:
    fixture, _config, _client = _world(tmp_path)
    _rollover_at(fixture, "console")
    assert len(store.list_rollover_runs(fixture["store"], 10)) == 1


def test_a_close_that_failed_heals_at_the_next_firing(tmp_path) -> None:
    """The defect: a failure held the day in closing for 24 hours. The
    next firing in the same day finishes the move."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=_clock, pick_seed="a" * 32,
             secret="b" * 64)
    store.update_day_status(fixture["store"], DAY, expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)
    instant = datetime.datetime(2026, 8, 12, 23, 0, tzinfo=datetime.UTC)
    latest = rollover.read_latest(fixture["store"])
    assert rollover.plan_step(latest, instant, "22:00") == "close"

    def failing(_path, _timeout):
        return rollover.Answer(400, {"cause": "close-failed"})

    run = rollover.run_and_record(
        root=fixture["store"], closes_at_utc="22:00", post=failing,
        now=lambda: instant, source="timer", say=lambda _line: None,
        retries=0, backoff_seconds=0.0, sleep=lambda _seconds: None)
    assert run.outcome == "failed"
    client = TestClient(create_app(config))

    def healed(path, _timeout):
        answer = client.post(path)
        return rollover.Answer(answer.status_code, answer.json())

    # An hour on, the same command finds the same step. The open at the
    # end of the rollover takes the current label, thus the clock moves
    # to the day that the label needs.
    later = instant + datetime.timedelta(hours=1)
    steps = rollover.run_rollover(
        root=fixture["store"], closes_at_utc="22:00", post=healed,
        now=lambda: later, say=lambda _line: None, retries=0,
        backoff_seconds=0.0, sleep=lambda _seconds: None)
    assert steps[:2] == ["close", "reveal"]


def test_the_timer_fires_hourly_with_catch_up() -> None:
    timer = (REPO / "deploy" / "starvector-day.timer").read_text()
    active = [line for line in timer.splitlines()
              if line and not line.startswith("#")]
    assert "OnCalendar=*-*-* *:00:00 UTC" in active
    assert "Persistent=true" in active


def test_the_rollover_unit_names_the_failure_alert() -> None:
    unit = (REPO / "deploy" / "starvector-day.service").read_text()
    assert "OnFailure=starvector-day-failed.service" in unit
    assert "SuccessExitStatus=2" in unit
    alert = (REPO / "deploy" / "starvector-day-failed.service").read_text()
    assert "service.rollover --alert" in alert


def test_the_alert_pings_the_fail_address(monkeypatch) -> None:
    pinged = []
    monkeypatch.setattr(rollover, "ping",
                        lambda url, *, failed, say: pinged.append(
                            (url, failed)))
    said = []
    rollover.alert_failure(url="https://example.invalid/x", say=said.append)
    assert pinged == [("https://example.invalid/x", True)]
    assert said


def test_the_alert_with_no_address_says_so(monkeypatch, capsys) -> None:
    monkeypatch.delenv("STARVECTOR_HEALTHCHECK_URL", raising=False)
    assert rollover.main(["--alert"]) == 0
    assert "only alert" in capsys.readouterr().out


# -- section 5: hardening -----------------------------------------------


def _door_world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    mint_player(config, player="ade", display_name="Ade",
                        clock=_clock, secret="1" * 43)
    client = TestClient(create_app(config, dev_mode=True, cookie_secure=False,
                                   operator_token=TOKEN))
    return fixture, client


def test_the_door_refuses_with_no_bearer(tmp_path) -> None:
    """A dev unit on the production store: a typed name was a sign-in
    as each player."""
    fixture, client = _door_world(tmp_path)
    constant = client.get("/api/dev/days")
    answer = client.post("/api/door", json={"player": "ade"})
    assert answer.status_code == 404
    assert answer.content == constant.content
    assert store.list_sessions(fixture["store"], "ade") == ()
    assert "set-cookie" not in answer.headers


def test_the_door_refuses_a_bad_bearer(tmp_path) -> None:
    fixture, client = _door_world(tmp_path)
    answer = client.post("/api/door", json={"player": "ade"},
                         headers={"Authorization": "Bearer nope"})
    assert answer.status_code == 404
    assert store.list_sessions(fixture["store"], "ade") == ()


def test_the_door_opens_with_the_bearer(tmp_path) -> None:
    fixture, client = _door_world(tmp_path)
    answer = client.post("/api/door", json={"player": "ade"}, headers=BEARER)
    assert answer.status_code == 200
    assert len(store.list_sessions(fixture["store"], "ade")) == 1


def test_the_door_mints_no_new_name_with_no_bearer(tmp_path) -> None:
    fixture, client = _door_world(tmp_path)
    assert client.post("/api/door",
                       json={"player": "walkin"}).status_code == 404
    assert store.read_player_or_none(fixture["store"], "walkin") is None


def test_write_once_syncs_the_file_and_the_directory(tmp_path,
                                                     monkeypatch) -> None:
    synced = []
    original = os.fsync

    def noting(handle):
        synced.append(os.fstat(handle))
        return original(handle)

    monkeypatch.setattr(os, "fsync", noting)
    path = tmp_path / "records" / "one.json"
    store.write_once_json(path, {"a": 1})
    import stat

    kinds = [stat.S_ISDIR(facts.st_mode) for facts in synced]
    assert kinds == [False, True]
    assert json.loads(path.read_text()) == {"a": 1}


def test_a_replacing_write_syncs_too(tmp_path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(os, "fsync", lambda handle: calls.append(handle))
    store._replace_json(tmp_path / "one.json", {"a": 1})
    assert len(calls) == 2


def test_a_second_write_once_still_refuses(tmp_path) -> None:
    path = tmp_path / "one.json"
    store.write_once_json(path, {"a": 1})
    with pytest.raises(store.StoreError):
        store.write_once_json(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}
    assert [entry.name for entry in tmp_path.iterdir()] == ["one.json"]


def test_the_write_bytes_are_the_earlier_bytes(tmp_path) -> None:
    """Rescoring compares rendered text, thus the sync must not move a
    byte."""
    from core.canonical import canonical_json_pretty

    path = tmp_path / "one.json"
    value = {"b": [1, 2], "a": "é"}
    store.write_once_json(path, value)
    assert path.read_text(encoding="utf-8") \
        == canonical_json_pretty(value) + "\n"


def test_the_access_log_holds_no_invite_token() -> None:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5", "GET", f"/join/ade.{'1' * 43}", "1.1", 302), None)
    assert limits.RedactInvitePaths().filter(record) is True
    assert "1" * 43 not in record.getMessage()
    assert "/join/[redacted]" in record.getMessage()


def test_the_filter_survives_the_uvicorn_logging_setup() -> None:
    """Uvicorn configures its loggers at start. The server adds the
    filter before that, thus the filter must stay on."""
    import uvicorn

    logger = logging.getLogger("uvicorn.access")
    added = limits.RedactInvitePaths()
    logger.addFilter(added)
    try:
        uvicorn.Config(lambda: None)
        assert added in logger.filters
    finally:
        logger.removeFilter(added)


def test_the_log_filter_leaves_other_paths_alone() -> None:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s %s',
        ("GET", "/api/day"), None)
    limits.RedactInvitePaths().filter(record)
    assert record.getMessage() == "GET /api/day"


def test_a_resident_context_serves_the_open(tmp_path, monkeypatch) -> None:
    """One copy of the pool at open when a resident context is there."""
    from service import day as day_module

    fixture, config = _played_world(tmp_path)
    client = TestClient(create_app(config, dev_mode=True))
    # Practice wires the resident context.
    assert client.post("/api/practice/score", json={
        "day": DAY, "record": mixed_wire_record()}).status_code == 200

    def refuses(*_arguments, **_keywords):
        raise AssertionError("the open wired a second copy of the pool")

    monkeypatch.setattr(day_module.scoring, "wire_for_open", refuses)
    monkeypatch.setattr(scoring, "load_pool_index", refuses)
    # The day label comes from the UTC calendar, thus this open needs
    # no named date.
    answer = client.post("/api/day/open")
    assert answer.status_code == 200, answer.text


def test_an_open_with_no_resident_context_still_needs_no_encoder(
        tmp_path, monkeypatch) -> None:
    """Spec S1 R5: an open spends nothing and needs no provider key."""
    fixture = build_service_fixture(tmp_path)
    client = TestClient(create_app(fixture["service_config"]))

    def refuses(*_arguments, **_keywords):
        raise AssertionError("the open wired the encoders")

    monkeypatch.setattr(scoring, "wire_for_close", refuses)
    assert client.post("/api/day/open").status_code == 200


def test_the_open_is_equal_with_and_without_the_resident_context(
        tmp_path) -> None:
    """The pick and the pinned identity are equal on the two paths, thus
    the close guard holds and the score stays byte-equal."""
    config_fixture = build_service_fixture(tmp_path / "one")
    config = config_fixture["service_config"]
    wired = scoring.wire_for_close(
        load_scoring_config(Path(config.scoring_config)),
        config.scoring_config, Path(config.data_root),
        config_fixture["providers"])
    resident = open_day(config, date=DAY, clock=_clock, pick_seed="a" * 32,
                        secret="b" * 64, trial_code="ABC123", wired=wired)
    plain_config = ServiceConfig(
        player=config.player, scoring_config=config.scoring_config,
        data_root=config.data_root,
        store_root=str(tmp_path / "other-store"), port=config.port)
    plain = open_day(plain_config, date=DAY, clock=_clock, pick_seed="a" * 32,
                     secret="b" * 64, trial_code="ABC123")
    assert resident == plain


def test_an_override_config_with_a_resident_context_refuses(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    with pytest.raises(ValueError):
        open_day(config, date=DAY, clock=_clock,
                 scoring_config_path="other.json", wired=object())


# -- section 5: the Caddyfile -------------------------------------------


def test_the_caddyfile_holds_the_cap_and_the_headers() -> None:
    caddy = (REPO / "deploy" / "Caddyfile").read_text()
    assert "max_size 1MiB" in caddy
    assert limits.BODY_BYTE_CAP == 1024 * 1024
    assert store.AVATAR_BYTE_CAP <= limits.BODY_BYTE_CAP
    for name in ("Strict-Transport-Security", "X-Content-Type-Options",
                 "X-Frame-Options", "Referrer-Policy", "Permissions-Policy",
                 "Content-Security-Policy"):
        assert name in caddy
    active = [line.strip() for line in caddy.splitlines()
              if not line.strip().startswith("#")]
    assert not any(re.match(r"^log\b", line) for line in active)


# -- section 7: the export ----------------------------------------------


def _flagged_world(tmp_path):
    """A world with the channel flag on in its scoring config, and
    its commonness tables built for the hash that flag makes."""
    from conftest import scoring_fakes
    from pipeline.commonness import (commonness_config_hash,
                                     ensure_commonness_tables)
    from pipeline.config import (element_config, intake_gates,
                                 outline_config, placement_config)
    from pipeline.context import load_pool_index
    from pipeline.score import Encoders
    from validation import harness

    fixture = build_service_fixture(tmp_path)
    path = Path(fixture["scoring_config_path"])
    document = json.loads(path.read_text())
    document["report"]["channel_scores"] = True
    flagged_path = tmp_path / "flagged.json"
    flagged_path.write_text(json.dumps(document, indent=2) + "\n")
    parsed = parse_scoring_config(document, str(flagged_path))
    providers = scoring_fakes(pair_count=24)
    data = fixture["data"]
    loaded = load_pool_index(Path(parsed.input.preparation_record), data,
                             dev_only=True)
    hashes = harness.scoring_provider_hashes(parsed, providers)
    commonness_hash = commonness_config_hash(
        parsed, loaded.render, hashes["sketch_encoder"],
        hashes["text_encoder"], hashes["sketch_pairs"], None)

    def background():
        return harness.full_background(
            parsed, providers["sketch_pairs"], "mixed", loaded.index,
            placement_config(parsed), data)

    ensure_commonness_tables(
        data_root=data, index=loaded.index, commonness_hash=commonness_hash,
        background=background, gates=intake_gates(parsed),
        render=loaded.render, outline=outline_config(parsed),
        element=element_config(parsed), placement=placement_config(parsed),
        encoders=Encoders(sketch=providers["sketch_encoder"],
                          text=providers["text_encoder"]),
        submission_mode="mixed", clock=_clock)
    return fixture, str(flagged_path)


def test_the_flag_stays_out_of_the_hash_when_off(tmp_path) -> None:
    """Each committed config keeps its hash (I4)."""
    from pipeline.config import config_to_json_value

    fixture = build_service_fixture(tmp_path)
    document = json.loads(Path(fixture["scoring_config_path"]).read_text())
    plain = parse_scoring_config(document, "plain")
    assert config_to_json_value(plain)["report"] == {"dev_only": True}
    document["report"]["channel_scores"] = False
    named_off = parse_scoring_config(document, "off")
    assert config_to_json_value(named_off) == config_to_json_value(plain)
    document["report"]["channel_scores"] = True
    on = parse_scoring_config(document, "on")
    assert config_to_json_value(on) != config_to_json_value(plain)


def test_the_flag_refuses_a_value_that_is_not_a_boolean(tmp_path) -> None:
    from pipeline.config import ConfigError

    fixture = build_service_fixture(tmp_path)
    document = json.loads(Path(fixture["scoring_config_path"]).read_text())
    document["report"]["channel_scores"] = "yes"
    with pytest.raises(ConfigError):
        parse_scoring_config(document, "bad")


def test_a_config_with_the_flag_off_writes_the_earlier_row(tmp_path) -> None:
    """The row of a config that does not name the flag has no new key."""
    fixture, _config = _played_world(tmp_path)
    row = store.read_json_or_none(
        store.trial_row_path(fixture["store"], DAY, "ade"))
    assert "channel_scores" not in row
    assert set(row) == {
        "day", "player", "trial_id", "p", "decoy_count", "beaten", "tied",
        "target_rank", "report", "scoring_config_hash",
        "commonness_config_hash", "preparation_version_id"}


def test_the_rescore_of_an_earlier_row_stays_byte_equal(tmp_path) -> None:
    fixture, config = _played_world(tmp_path)
    counts = rescore_days(config, config_path=config.scoring_config,
                          providers=fixture["providers"])
    assert counts["compared"] == counts["equal"] == 1


def test_a_config_with_the_flag_on_stores_channel_scores(tmp_path) -> None:
    fixture, flagged = _flagged_world(tmp_path)
    config = ServiceConfig(
        player="ade", scoring_config=flagged,
        data_root=str(fixture["data"]), store_root=str(fixture["store"]),
        port=8399)
    open_day(config, date=DAY, clock=_clock, pick_seed="a" * 32,
             secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "e" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(config, providers=fixture["providers"], clock=_clock)
    row = store.read_json_or_none(
        store.trial_row_path(fixture["store"], DAY, "ade"))
    channels = row["channel_scores"]
    assert channels
    for value in channels.values():
        assert set(value) == {"standardized", "p"}
        assert 0.0 <= value["p"] <= 1.0
    # A rescore with the pinned config reproduces the new row too.
    assert rescore_days(
        config, config_path=flagged,
        providers=fixture["providers"])["equal"] == 1
    # The reveal builds the index, and the table holds the values.
    reveal_day(config, clock=_clock)
    target = index.index_path(fixture["data"])
    with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT channel, standardized, p, pinned FROM trial_channels"
        ).fetchall()
    assert {row[0] for row in rows} == set(channels)
    assert all(row[3] == 1 for row in rows)
    # No player surface reads them (spec PL1 section 7).
    client = TestClient(create_app(config))
    assert "channel_scores" not in client.get(f"/api/reveal?day={DAY}").text
    assert "channel_scores" not in client.get("/api/me/export").text


def test_the_reveal_builds_the_index(tmp_path) -> None:
    fixture, _config = _played_world(tmp_path)
    target = index.index_path(fixture["data"])
    assert target.name == "results-v2.sqlite"
    assert index.read_fingerprint(target) \
        == index.store_fingerprint(fixture["store"])


def test_a_failed_index_build_does_not_undo_the_reveal(tmp_path, monkeypatch,
                                                       capsys) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=_clock, pick_seed="a" * 32,
             secret="b" * 64)
    close_day(config, providers=fixture["providers"], clock=_clock)

    def refuses(*_arguments, **_keywords):
        raise index.ResultsIndexError("no room")

    monkeypatch.setattr(index, "build", refuses)
    record = reveal_day(config, clock=_clock)
    assert record.status == "revealed"
    assert "no room" in capsys.readouterr().err


def test_trial_atoms_has_pinned_and_a_rescore_does_not_double_count(
        tmp_path) -> None:
    fixture, _config = _played_world(tmp_path)
    root = fixture["store"]
    pinned = store.read_json_or_none(store.trial_row_path(root, DAY, "ade"))
    store.write_once_json(
        store.trial_row_path(root, DAY, "ade", "abcd1234"),
        {**pinned, "scoring_config_hash": "abcd1234" + "0" * 56})
    target = index.index_path(fixture["data"])
    index.build(root, target)
    with sqlite3.connect(f"file:{target}?mode=ro", uri=True) as connection:
        every = connection.execute(
            "SELECT COUNT(*) FROM trial_atoms").fetchone()[0]
        kept = connection.execute(
            "SELECT COUNT(*) FROM trial_atoms WHERE pinned = 1").fetchone()[0]
    assert every == 2 * kept > 0


def test_the_console_example_counts_pinned_rows() -> None:
    source = (REPO / "web/src/dev/index-tab.tsx").read_text()
    words = source[source.index("Words that connected"):]
    assert "pinned = 1" in words[:words.index("LIMIT 50")]


def test_the_operator_reader_reports_a_cut(tmp_path) -> None:
    fixture, _config = _played_world(tmp_path)
    target = index.index_path(fixture["data"])
    rows, truncated = index.revealed_trial_rows(target)
    assert (len(rows), truncated) == (1, False)
    rows, truncated = index.revealed_trial_rows(target, limit=0)
    assert (rows, truncated) == ([], True)


def test_the_operator_path_says_when_it_cut(tmp_path, monkeypatch) -> None:
    fixture, config = _played_world(tmp_path)
    mint_player(config, player="ade", display_name="Ade",
                        clock=_clock, secret="1" * 43)
    monkeypatch.setattr(index, "revealed_trial_rows",
                        lambda _target, **_keywords: ([{"day": DAY}], True))
    client = TestClient(create_app(config, operator_token=TOKEN))
    body = client.get("/api/ops/trials", headers=BEARER).json()
    assert body["truncated"] is True
    assert body["row_cap"] == index.TRIAL_ROW_CAP
    assert body["count"] == 1


def test_the_guide_states_the_fence() -> None:
    guide = (REPO / "docs" / "querying-results.md").read_text()
    assert "I6" in guide
    assert "sqlite3 -readonly" in guide
    assert "json_each" in guide
    assert "duckdb" in guide.lower()
    assert "results-v2.sqlite" in guide


def _guide_sql(heading: str) -> list[str]:
    """The fenced SQL of one section of the query document."""
    guide = (REPO / "docs" / "querying-results.md").read_text()
    section = guide.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"```sql\n(.*?)```", section, flags=re.DOTALL)


def test_each_sqlite_example_of_the_guide_runs(tmp_path) -> None:
    """The queries of the document against a built index, read-only."""
    fixture, _config = _played_world(tmp_path)
    target = index.index_path(fixture["data"])
    examples = _guide_sql("With sqlite3")
    assert len(examples) == 5
    connection = index.connect(target)
    try:
        answers = [connection.execute(sql).fetchall() for sql in examples]
    finally:
        connection.close()
    assert answers[0][0]["player"] == "ade"
    assert answers[1]
    assert answers[2] == []     # The fixture config has the flag off.
    # The fixture record holds two strokes of five points, and two words.
    assert [row["points"] for row in answers[3]] == [5, 5]
    assert [row["word"] for row in answers[4]] \
        == ["tall vertical structure", "cold and exposed"]


def test_the_read_only_open_refuses_a_write(tmp_path) -> None:
    fixture, _config = _played_world(tmp_path)
    connection = index.connect(index.index_path(fixture["data"]))
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM trials")
    finally:
        connection.close()


def test_each_duckdb_example_of_the_guide_runs(tmp_path) -> None:
    """Runs with `uv run --with duckdb pytest`. The extension download
    needs the network one time, thus an offline box skips this."""
    duckdb = pytest.importorskip("duckdb")
    fixture, _config = _played_world(tmp_path)
    target = index.index_path(fixture["data"])
    connection = duckdb.connect()
    try:
        connection.execute("INSTALL sqlite; LOAD sqlite;")
    except duckdb.Error as error:
        pytest.skip(f"the sqlite extension is not available: {error}")
    first, second = _guide_sql("With DuckDB")
    statements = [text.strip() for text in first.split(";") if text.strip()]
    attach = statements[2].replace("data/index/results-v2.sqlite", str(target))
    connection.execute(attach)
    assert connection.execute(statements[3]).fetchall()[0][0] == "ade"
    assert connection.execute(second).fetchall()[0][2] == 2
    connection.close()
    # DuckDB left the file as it was: a read-only attach writes nothing.
    assert index.read_fingerprint(target) \
        == index.store_fingerprint(fixture["store"])


def test_the_console_names_the_next_firing_when_a_step_waits(tmp_path) -> None:
    """A day in closing moves at the next hour and not the next close."""
    from service import console

    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY, clock=_clock,
             pick_seed="a" * 32, secret="b" * 64)
    store.update_day_status(fixture["store"], DAY, expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)
    instant = datetime.datetime(2026, 8, 12, 22, 30, tzinfo=datetime.UTC)
    view = console.schedule_view(fixture["store"], closes_at_utc="22:00",
                                 instant=instant, lock_held=False)
    assert view["next_run"]["at"] == "2026-08-12T23:00:00+00:00"
