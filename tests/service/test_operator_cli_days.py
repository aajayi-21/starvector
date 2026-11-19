"""Integration: the day moves and the schedule of the operator command
(spec OC1 section 4, rulings D1 and D6, build item OC1.6).

A day move goes to the public server, which is a test client of the
app with dev mode off. Each move holds the rollover lock with no wait,
asks its question, and writes its two journal records.
"""

import json
import os

from sv_world import (FIRST_DAY, HOUR, LOGIN, OPEN_DAY, TOKEN, build_vp1_world,
                      build_world, config_file, put_a_newer_day_in_front, sv)
from svc_fixture import FIXED_CLOCK

from service import beacon, operator_cli, rollover, store
from service.day import close_day

NOTE = "zebra-marker holiday note"


def _pair(world, command: str):
    """The `start` record and the `end` record of the one command of
    this name in the journal."""
    records = [entry for entry in world.journal() if entry.command == command]
    assert [entry.phase for entry in records] == ["start", "end"], command
    start, end = records
    assert start.entry_id == end.entry_id and start.login == LOGIN
    return start, end


def _journal_bytes(world) -> bytes:
    folder = store.operator_journal_dir(world.root)
    return b"".join(path.read_bytes() for path in sorted(folder.iterdir()))


def _status(world, day: str) -> str:
    return store.read_day_record(world.root, day).status


# ---- close, reveal, open ----


def test_close_reveal_and_open_move_the_day_through_the_server(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "day", "close") == 0
    captured = capsys.readouterr()
    assert (f"Close {OPEN_DAY}? New sends stop, and each send is scored "
            "now.") in captured.err
    assert captured.out == f"day {OPEN_DAY} closed  trial_rows=1  " \
                           "quarantined=0\n"
    assert _status(world, OPEN_DAY) == "closed"
    # The body names the day of the question, also for the latest day,
    # and a close has the long time limit.
    start, end = _pair(world, "day close")
    # The body names the record of this command too, thus the server
    # writes no second record for the move (spec OC1 section 13).
    assert world.sent == [("POST", "/api/day/close",
                           {"day": OPEN_DAY,
                            "journal_entry": start.entry_id}, 900.0)]
    assert start.login == "opal"
    assert start.day == end.day == OPEN_DAY and start.facts == {}
    assert end.outcome == "done"
    assert end.facts == {"trial_rows": 1, "quarantined": 0}

    assert sv(world, "day", "reveal", "--json") == 0
    captured = capsys.readouterr()
    assert f"Reveal {OPEN_DAY}? Players see the photo" in captured.err
    assert json.loads(captured.out) == {"day": OPEN_DAY}
    assert _status(world, OPEN_DAY) == "revealed"
    start, end = _pair(world, "day reveal")
    assert world.sent[-1] == ("POST", "/api/day/reveal",
                              {"day": OPEN_DAY,
                               "journal_entry": start.entry_id}, 120.0)
    assert start.day == OPEN_DAY and end.outcome == "done"

    # The open has no question, and the server gives the label.
    world.prompts.clear()
    assert sv(world, "day", "open") == 0
    captured = capsys.readouterr()
    assert "day 2026-08-13 open" in captured.out
    assert "trial code " in captured.out and "commitment " in captured.out
    assert world.prompts == [] and captured.err == ""
    assert _status(world, "2026-08-13") == "open"
    start, end = _pair(world, "day open")
    assert start.day is None and end.day == "2026-08-13"
    assert end.outcome == "done"
    assert sv(world, "log", "--command", "day open") == 0
    assert "day open  day=2026-08-13  done" in capsys.readouterr().out
    # The lock is free after each move.
    handle = rollover.hold_lock(store.rollover_lock_path(world.root))
    assert handle is not None
    os.close(handle)


def test_a_named_day_behind_the_latest_one_closes_and_reveals(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    newer = put_a_newer_day_in_front(world)
    assert store.latest_day(world.root) == newer

    assert sv(world, "day", "close", OPEN_DAY) == 0
    captured = capsys.readouterr()
    assert (f"{OPEN_DAY} is still open behind a newer day. Close it and "
            "score its sends?") in captured.err
    assert world.sent[-1][:2] == ("POST", "/api/day/close")
    assert world.sent[-1][2]["day"] == OPEN_DAY
    assert _status(world, OPEN_DAY) == "closed"

    assert sv(world, "day", "reveal", OPEN_DAY) == 0
    captured = capsys.readouterr()
    assert f"{OPEN_DAY} stayed closed behind a newer day" in captured.err
    assert world.sent[-1][:2] == ("POST", "/api/day/reveal")
    assert world.sent[-1][2]["day"] == OPEN_DAY
    assert _status(world, OPEN_DAY) == "revealed"
    assert _status(world, newer) == "revealed"
    for command in ("day close", "day reveal"):
        start, end = _pair(world, command)
        assert start.day == end.day == OPEN_DAY and end.outcome == "done"


def test_a_day_move_refuses_a_day_it_cannot_move(tmp_path, monkeypatch,
                                                 capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for argv, text in (
            (("day", "close", "2026-01-01"), "no stored day '2026-01-01'"),
            (("day", "reveal", "2026-01-01"), "no stored day '2026-01-01'"),
            (("day", "close", FIRST_DAY), "a close is for a day that is open"),
            (("day", "reveal"), "a reveal is for a day that is closed"),
            (("day", "reveal", OPEN_DAY), f"{OPEN_DAY} is open")):
        assert sv(world, *argv) == 1, argv
        assert text in capsys.readouterr().err
    # Each refusal comes before the question, the server, and the journal.
    assert world.prompts == [] and world.sent == []
    assert world.journal() == ()


def test_a_day_move_asks_first(tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "day", "close", stdin_is_tty=False) == 1
    assert "the standard input is not a terminal" in capsys.readouterr().err
    world.answer = "no"
    assert sv(world, "day", "close") == 1
    assert "the answer was not yes" in capsys.readouterr().err
    assert world.sent == [] and world.journal() == ()
    assert _status(world, OPEN_DAY) == "open"

    assert sv(world, "day", "close", "--yes", stdin_is_tty=False) == 0
    capsys.readouterr()
    assert _status(world, OPEN_DAY) == "closed"
    assert world.prompts == ["Type yes to continue: "]


def test_a_close_that_stopped_gets_the_question_of_its_end(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    store.update_day_status(world.root, OPEN_DAY, expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)
    assert sv(world, "day", "close") == 0
    assert f"Finish closing {OPEN_DAY}?" in capsys.readouterr().err
    assert _status(world, OPEN_DAY) == "closed"


# ---- the lock and the server ----


def test_a_rollover_that_holds_the_lock_gives_the_exit_code_2(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch, hour=HOUR,
                        instant="2026-08-12T22:30:00")
    handle = rollover.hold_lock(store.rollover_lock_path(world.root))
    try:
        for argv in (("day", "open"), ("day", "close"),
                     ("day", "reveal", OPEN_DAY), ("schedule", "run")):
            assert sv(world, *argv) == 2, argv
            captured = capsys.readouterr()
            assert captured.out == ""
            assert "a rollover is at work" in captured.err
    finally:
        os.close(handle)
    assert world.prompts == [] and world.sent == []
    assert world.journal() == ()
    assert _status(world, OPEN_DAY) == "open"


def test_a_lock_that_a_rollover_gets_after_the_question_stops_the_move(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    held: list[int] = []

    def answer_while_a_rollover_starts(_prompt: str) -> str:
        held.append(rollover.hold_lock(store.rollover_lock_path(world.root)))
        return "yes"

    try:
        assert sv(world, "day", "close",
                  ask=answer_while_a_rollover_starts) == 2
    finally:
        os.close(held[0])
    assert "a rollover is at work" in capsys.readouterr().err
    assert world.sent == [] and world.journal() == ()


def test_a_server_that_does_not_answer_is_a_recorded_failure(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    # The sender of the process, at an address where nothing listens.
    assert sv(world, "day", "close", "--base-url", "http://127.0.0.1:9",
              call=None) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "failed: the server did not answer at http://127.0.0.1:9" \
        in captured.err
    assert _status(world, OPEN_DAY) == "open"
    start, end = _pair(world, "day close")
    assert start.day == OPEN_DAY
    assert (end.outcome, end.error_kind) == ("failed", "TransportError")
    handle = rollover.hold_lock(store.rollover_lock_path(world.root))
    assert handle is not None
    os.close(handle)


def test_a_bearer_that_the_server_refuses_names_the_token_variable(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    wrong = "not-the-token-of-the-server"

    def call(method, path, body, _timeout):
        answer = world.client.request(
            method, path, json=body,
            headers={"Authorization": f"Bearer {wrong}"})
        return rollover.Answer(status=answer.status_code, body=answer.json())

    environ = {operator_cli.TOKEN_VARIABLE: wrong}
    for argv in (("day", "close"), ("day", "open")):
        assert sv(world, *argv, call=call, environ=environ) == 1
        captured = capsys.readouterr()
        assert "refused: the server refused the operator token" \
            in captured.err
        assert "STARVECTOR_OPERATOR_TOKEN" in captured.err
        assert "sudo sv" in captured.err
        # The command prints no token: not the one it has, and not the
        # one of the server.
        for token in (wrong, TOKEN):
            assert token not in captured.out + captured.err
    assert _status(world, OPEN_DAY) == "open"
    ends = [entry for entry in world.journal() if entry.phase == "end"]
    assert [(entry.outcome, entry.error_kind) for entry in ends] \
        == [("refused", "http-401")] * 2
    assert wrong.encode() not in _journal_bytes(world)


def test_a_refusal_of_the_server_prints_and_stays_out_of_the_journal(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    # The latest day is open: the server refuses a new day.
    assert sv(world, "day", "open") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused: the server answered HTTP 409" in captured.err
    assert "reveal it before a new day opens" in captured.err
    start, end = _pair(world, "day open")
    assert start.day is None and end.day is None
    assert (end.outcome, end.error_kind) == ("refused", "http-409:refused")
    assert b"reveal it before" not in _journal_bytes(world)


def test_a_server_error_is_a_failure(tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)

    def call(_method, _path, _body, _timeout):
        return rollover.Answer(status=503, body={"detail": "\x1b[31mdown"})

    assert sv(world, "day", "close", call=call) == 1
    captured = capsys.readouterr()
    assert "failed: the server answered HTTP 503: \\x1b[31mdown" \
        in captured.err
    _start, end = _pair(world, "day close")
    assert (end.outcome, end.error_kind) == ("failed", "http-503")


def test_a_vp1_close_before_its_time_prints_the_refusal_of_the_server(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_vp1_world(tmp_path, monkeypatch,
                            instant="2026-08-12T12:00:00")
    # The fake beacon has each pulse with no wait. This one has its pulse
    # in the year 2100, as the public beacon has it after the close.
    monkeypatch.setattr(beacon.FakeBeacon, "ready_at",
                        lambda _self, _number: 4_102_444_800)
    assert sv(world, "day", "close") == 1
    captured = capsys.readouterr()
    assert "refused: the server answered HTTP 409" in captured.err
    assert "close it at its scheduled close" in captured.err
    record = store.read_day_record(world.root, OPEN_DAY)
    assert record.status == "open" and record.target_id is None
    _start, end = _pair(world, "day close")
    assert (end.outcome, end.error_kind) == ("refused", "http-409:refused")

    # The views of the day say that no target is there to show or hide.
    assert sv(world, "day", "show") == 0
    out = capsys.readouterr().out
    assert "no target until the close" in out and "not shown" not in out


# ---- the pause ----


def test_pause_and_resume_write_the_control_and_no_note_in_the_journal(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch, hour=HOUR)
    assert sv(world, "schedule", "pause", "--note", NOTE) == 0
    captured = capsys.readouterr()
    assert f"paused yes  changed {world.clock.instant.isoformat()}  " \
           f"note: {NOTE}" in captured.out
    assert captured.err == "" and world.prompts == []
    control = store.read_rollover_control(world.root)
    assert control == store.RolloverControl(
        paused=True, changed_at=world.clock.instant.isoformat(), note=NOTE)
    start, end = _pair(world, "schedule pause")
    assert start.facts == end.facts == {"paused": True}
    assert end.outcome == "done"
    assert NOTE.encode() not in _journal_bytes(world)
    assert b"zebra" not in _journal_bytes(world)

    assert sv(world, "schedule", "resume", "--json") == 0
    value = json.loads(capsys.readouterr().out)
    assert value["paused"] is False and value["pause_note"] == ""
    assert store.read_rollover_control(world.root).paused is False
    _start, end = _pair(world, "schedule resume")
    assert end.facts == {"paused": False}

    # A note that the store refuses stops before the journal.
    for note in ("x" * 201, "two\nlines"):
        assert sv(world, "schedule", "pause", "--note", note) == 1
        assert "refused:" in capsys.readouterr().err
    assert len(world.journal()) == 4
    assert store.read_rollover_control(world.root).paused is False


# ---- the rollover of the command ----


def test_schedule_run_moves_the_day_while_the_days_are_paused(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch, hour=HOUR,
                        instant="2026-08-12T22:30:00")
    assert sv(world, "schedule", "pause", "--note", NOTE) == 0
    capsys.readouterr()
    assert sv(world, "schedule", "run") == 0
    captured = capsys.readouterr()
    assert (f"Close {OPEN_DAY} and score it, then Reveal {OPEN_DAY}, then "
            "Open 2026-08-13") in captured.err
    # Ruling D6: the question says that the pause does not stop this.
    assert "The automatic days are paused" in captured.err
    assert "does not read the pause" in captured.err
    assert "rollover moved: close, reveal, open" in captured.out
    assert _status(world, OPEN_DAY) == "revealed"
    assert store.latest_day(world.root) == "2026-08-13"
    assert store.read_rollover_control(world.root).paused is True

    (run,) = store.list_rollover_runs(world.root, 5)
    assert run.source == "command-line" and run.outcome == "moved"
    assert run.steps == ("close", "reveal", "open")
    start, end = _pair(world, "schedule run")
    assert start.facts == {"steps": ("close", "reveal", "open"),
                           "retries": 0}
    assert end.facts == start.facts and end.outcome == "done"
    assert end.day is None and end.player is None

    # A second run in the same minute has nothing to do.
    assert sv(world, "schedule", "run") == 1
    assert "Nothing is due now." in capsys.readouterr().err
    assert len(store.list_rollover_runs(world.root, 5)) == 1
    assert len(world.journal()) == 4


def test_schedule_run_with_no_pause_asks_the_plain_question(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch, hour=HOUR,
                        instant="2026-08-12T22:30:00")
    assert sv(world, "schedule", "run", "--json", "--yes") == 0
    captured = capsys.readouterr()
    assert "paused" not in captured.err.split("rollover:")[0]
    value = json.loads(captured.out)
    assert value["run"]["source"] == "command-line"
    assert value["run"]["steps"] == ["close", "reveal", "open"]
    assert value["schedule"]["latest"]["day"] == "2026-08-13"
    # The lines of the rollover go to the error stream.
    assert "rollover: close" in captured.err


def test_schedule_run_needs_the_rollover_hour(tmp_path, monkeypatch,
                                              capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "schedule", "run") == 1
    assert "closes_at_utc" in capsys.readouterr().err
    assert world.journal() == () and world.sent == []


def test_a_rollover_that_stops_records_the_steps_before_the_stop(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch, hour=HOUR,
                        instant="2026-08-12T22:30:00")

    def call(method, path, body, timeout):
        if path.endswith("/reveal"):
            return rollover.Answer(status=500, body={"detail": "boom"})
        return world.call(method, path, body, timeout)

    assert sv(world, "schedule", "run", call=call) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "failed: the rollover did not complete" in captured.err
    assert _status(world, OPEN_DAY) == "closed"
    (run,) = store.list_rollover_runs(world.root, 5)
    assert run.outcome == "failed" and run.steps == ("close",)
    start, end = _pair(world, "schedule run")
    assert start.facts["steps"] == ("close", "reveal", "open")
    assert end.facts == {"steps": ("close",), "retries": 0}
    assert (end.outcome, end.error_kind) == ("failed", "rollover-failed")
    assert b"boom" not in _journal_bytes(world)


def test_the_config_of_the_command_gives_the_default_address(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    close_day(world.config, clock=lambda: FIXED_CLOCK)
    # Port 9 answers nothing: the default address is the config port.
    world.path = config_file(tmp_path, world.config, name="port.json", port=9)
    assert sv(world, "day", "reveal", call=None) == 1
    assert "did not answer at http://127.0.0.1:9" in capsys.readouterr().err
