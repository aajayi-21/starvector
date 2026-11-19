"""Integration: the operator command and its reads (spec OC1 section
3.1, build item OC1.4).

Each read prints its facts as text and as JSON. The target, the
credit, and the scores of a day that is not revealed are in no output.
A control character that a player wrote does not go to the terminal.
"""

import io
import json
import os
import stat

import pytest
from sv_world import (FIRST_DAY, HOUR, LOGIN, OPEN_DAY, build_world,
                      config_file, send, sv)
from svc_fixture import FIXED_CLOCK, mixed_wire_record

from service import access, index, operator_cli, rollover, store
from service import operator_plan as plan
from service.day import close_day

ESCAPE = "\x1b"
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 24
# A trial score that no stored trial row of the world has.
PLANTED_SCORE = 0.424242


def _json(capsys) -> object:
    return json.loads(capsys.readouterr().out)


def _plant_open_trial_row(world) -> None:
    """Give the open day a trial row, as a close does when it stops
    before its end. No output of an open day shows its numbers."""
    stored = store.read_json_or_none(
        store.trial_row_path(world.root, FIRST_DAY, "bru"))
    store.write_once_json(
        store.trial_row_path(world.root, OPEN_DAY, "ade"),
        {**stored, "day": OPEN_DAY, "player": "ade", "p": PLANTED_SCORE})


def _targets(world) -> tuple[str, str]:
    """The target of the revealed day and the target of the open day."""
    shown = store.read_day_record(world.root, FIRST_DAY).target_id
    hidden = store.read_day_record(world.root, OPEN_DAY).target_id
    assert shown != hidden
    return shown, hidden


# ---- the reads ----


def test_status_names_the_day_the_players_and_the_server(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "status") == 0
    out = capsys.readouterr().out
    assert f"latest {OPEN_DAY}" in out and "open  sends=1" in out
    assert "automatic days off" in out
    assert "players active=2" in out
    assert "public server answers" in out
    assert world.sent[0][:3] == ("GET", "/api/about", None)

    assert sv(world, "status", "--json") == 0
    value = _json(capsys)
    assert value["latest"]["day"] == OPEN_DAY
    assert value["players"] == {"active": 2}
    assert value["server_answers"] is True
    assert value["schedule"]["paused"] is False


def test_status_says_when_the_server_does_not_answer(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    # The sender of the process, at an address where nothing listens.
    assert sv(world, "status", "--base-url", "http://127.0.0.1:9",
              call=None) == 0
    assert "public server does not answer" in capsys.readouterr().out


def test_days_and_day_show_print_each_day(tmp_path, monkeypatch,
                                          capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "days") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"{OPEN_DAY}  ") and "open" in lines[0]
    assert lines[1].startswith(f"{FIRST_DAY}  ") and "revealed" in lines[1]

    assert sv(world, "day", "show", FIRST_DAY) == 0
    out = capsys.readouterr().out
    shown, _hidden = _targets(world)
    assert f"target {shown}" in out
    assert "credit Test photo" in out and "Wikimedia Commons" in out
    assert "sends 1" in out and "bru" in out and "Bru Lin" in out
    assert "p=" in out and "rank=" in out

    # With no day, the command shows the latest one.
    assert sv(world, "day", "show", "--json") == 0
    value = _json(capsys)
    assert value["day"] == OPEN_DAY and value["status"] == "open"
    assert [row["player"] for row in value["sends"]] == ["ade"]
    assert value[plan.VISIBILITY_KEY] == "hidden"


def test_no_read_shows_the_target_of_a_day_that_is_not_revealed(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    _plant_open_trial_row(world)
    shown, hidden = _targets(world)
    credit = store.read_day_record(world.root, OPEN_DAY)
    position = world.fixture["image_ids"].index(credit.target_id)
    hidden_texts = (hidden, f"Test photo {position}",
                    f"Test_photo_{position}", str(PLANTED_SCORE))
    commands = (("days",), ("day", "show", OPEN_DAY), ("day", "show"),
                ("status",), ("players", "history", "ade"),
                ("players", "history", "bru"))
    for command in commands:
        for flags in ((), ("--json",)):
            assert sv(world, *command, *flags) == 0, command
            out = capsys.readouterr().out
            for text in hidden_texts:
                assert text not in out, (command, flags, text)

    # The same reads show the target of the revealed day.
    stored = store.read_json_or_none(
        store.trial_row_path(world.root, FIRST_DAY, "bru"))
    assert sv(world, "days", "--json") == 0
    rows = {row["day"]: row for row in _json(capsys)["days"]}
    assert rows[FIRST_DAY]["target_id"] == shown
    assert "target_id" not in rows[OPEN_DAY]
    assert sv(world, "day", "show", FIRST_DAY, "--json") == 0
    value = _json(capsys)
    assert value["target_id"] == shown
    assert value["credit"]["source"] == "Wikimedia Commons"
    assert value["sends"][0]["trial"]["p"] == stored["p"]
    assert sv(world, "players", "history", "bru", "--json") == 0
    days = {row["day"]: row for row in _json(capsys)["days"]}
    assert days[FIRST_DAY]["target_id"] == shown
    assert days[FIRST_DAY]["trial"]["p"] == stored["p"]
    assert "target_id" not in days[OPEN_DAY]
    assert sv(world, "players", "history", "bru") == 0
    assert f"p={stored['p']}" in capsys.readouterr().out


def test_a_closed_day_stays_hidden_until_its_reveal(tmp_path, monkeypatch,
                                                    capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    _shown, hidden = _targets(world)
    close_day(world.config, clock=lambda: FIXED_CLOCK)
    stored = store.read_json_or_none(
        store.trial_row_path(world.root, OPEN_DAY, "ade"))
    for command in (("days",), ("day", "show", OPEN_DAY), ("status",),
                    ("players", "history", "ade")):
        for flags in ((), ("--json",)):
            assert sv(world, *command, *flags) == 0
            out = capsys.readouterr().out
            assert hidden not in out, (command, flags)
            assert f"\"p\": {stored['p']}" not in out
            assert f"p={stored['p']}" not in out
    assert sv(world, "day", "show", OPEN_DAY) == 0
    assert "target not shown: the day is not revealed" \
        in capsys.readouterr().out


def test_day_send_prints_one_stored_send(tmp_path, monkeypatch,
                                         capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "day", "send", OPEN_DAY, "ade") == 0
    out = capsys.readouterr().out
    assert "impression: tall vertical structure" in out
    assert "group: tower (g1)" in out
    assert "relation: tower (g1) left-of sea (g2)" in out
    assert sv(world, "day", "send", OPEN_DAY, "ade", "--json") == 0
    assert _json(capsys)["record"] == mixed_wire_record()

    assert sv(world, "day", "send", OPEN_DAY, "bru") == 1
    assert "refused: bru has no stored send" in capsys.readouterr().err
    assert sv(world, "day", "send", "2026-01-01", "ade") == 1
    assert "no stored day '2026-01-01'" in capsys.readouterr().err
    assert sv(world, "day", "show", "2026-01-01") == 1
    assert "no stored day" in capsys.readouterr().err


def test_a_control_character_does_not_go_to_the_terminal(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    record = mixed_wire_record()
    record["impressions"] = [f"{ESCAPE}[31mred{ESCAPE}]0;title\x07"]
    send(world, OPEN_DAY, "bru", record)
    store.set_account_description(world.root, "bru", "line one\nline two",
                                  timestamp=FIXED_CLOCK)
    for flags in ((), ("--json",)):
        assert sv(world, "day", "send", OPEN_DAY, "bru", *flags) == 0
        out = capsys.readouterr().out
        assert ESCAPE not in out and "\x07" not in out
        assert ("\\x1b[31mred" in out) or ("\\u001b[31mred" in out)
    # A legal description holds a line end, and it stays on one line.
    assert sv(world, "players", "show", "bru") == 0
    assert "description: line one\\nline two" in capsys.readouterr().out

    # The store refuses a description with an ESC character. A file
    # with one, from a different computer, gives a refusal and no raw
    # character.
    path = store.account_record_path(world.root, "bru")
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["description"] = f"{ESCAPE}[2Jcleared"
    path.write_text(json.dumps(raw), encoding="utf-8")
    for flags in ((), ("--json",)):
        assert sv(world, "players", "show", "bru", *flags) == 1
        captured = capsys.readouterr()
        assert ESCAPE not in captured.out + captured.err
        assert "refused:" in captured.err


def test_schedule_prints_the_hour_and_the_due_steps(tmp_path, monkeypatch,
                                                    capsys) -> None:
    world = build_world(tmp_path, monkeypatch, hour=HOUR,
                        instant="2026-08-12T22:30:00")
    assert sv(world, "schedule") == 0
    out = capsys.readouterr().out
    assert f"rollover hour {HOUR} UTC" in out
    assert "paused no" in out
    assert "due now: close, reveal, open 2026-08-13" in out
    assert sv(world, "schedule", "--json") == 0
    value = _json(capsys)
    assert value["due_now"]["steps"] == ["close", "reveal", "open"]
    assert value["latest"]["day"] == OPEN_DAY
    assert value["lock_held"] is False


def test_the_player_reads_print_the_roster_and_one_account(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    access.open_session(world.root, "ade", user_agent="Firefox",
                        instant=world.clock.instant)
    assert sv(world, "players", "list") == 0
    out = capsys.readouterr().out
    assert "ade  active  devices=1  sends=1" in out
    assert "bru  active  devices=0  sends=1" in out and "Bru Lin" in out
    assert sv(world, "players", "list", "--json") == 0
    assert [row["player"] for row in _json(capsys)["players"]] \
        == ["ade", "bru"]

    assert sv(world, "players", "show", "ade") == 0
    out = capsys.readouterr().out
    assert "display name Ade" in out and "devices 1" in out
    assert "operator code none" in out
    assert sv(world, "players", "show", "ade", "--json") == 0
    value = _json(capsys)
    assert value["sends"] == 1 and len(value["sessions"]) == 1

    assert sv(world, "players", "history", "ade") == 0
    out = capsys.readouterr().out
    assert f"{OPEN_DAY}" in out and "sent=yes" in out and "sent=no" in out

    assert sv(world, "players", "show", "nobody") == 1
    assert "no stored player 'nobody'" in capsys.readouterr().err
    assert sv(world, "players", "show", "Not A Name") == 1
    assert "refused:" in capsys.readouterr().err


def test_the_avatar_goes_to_a_new_file_alone(tmp_path, monkeypatch,
                                             capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    target = tmp_path / "ade.png"
    assert sv(world, "players", "avatar", "ade", "--save", str(target)) == 1
    assert "ade has no avatar" in capsys.readouterr().err
    assert not target.exists()

    store.set_account_avatar(world.root, "ade", PNG, timestamp=FIXED_CLOCK)
    assert sv(world, "players", "avatar", "ade", "--save", str(target)) == 0
    assert "wrote the avatar of ade" in capsys.readouterr().out
    assert target.read_bytes() == PNG
    assert stat.S_IMODE(target.stat().st_mode) == 0o600

    # A path that is there refuses, and the file stays as it was.
    target.write_bytes(b"mine")
    assert sv(world, "players", "avatar", "ade", "--save", str(target)) == 1
    assert "is there" in capsys.readouterr().err
    assert target.read_bytes() == b"mine"


def test_the_index_reads_describe_check_and_list(tmp_path, monkeypatch,
                                                 capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "db", "status") == 0
    out = capsys.readouterr().out
    assert "exists yes" in out and "revealed_trials  rows=1" in out
    assert sv(world, "db", "status", "--json") == 0
    assert _json(capsys)["exists"] is True

    # The index of the world is from the first reveal: the open day is
    # not in it, and the exit code says so.
    assert sv(world, "db", "verify") == 1
    assert "the index does not agree with the store" \
        in capsys.readouterr().out
    index.build(world.root, index.index_path(world.fixture["data"]))
    assert sv(world, "db", "verify") == 0
    assert "the index agrees with the store" in capsys.readouterr().out
    send(world, OPEN_DAY, "bru")
    assert sv(world, "db", "verify", "--json") == 1
    value = _json(capsys)
    assert value["agrees"] is False and value["problems"]

    assert sv(world, "db", "trials") == 0
    out = capsys.readouterr().out
    assert out.startswith(f"{FIRST_DAY}  bru  p=")
    assert sv(world, "db", "trials", "--player", "ade", "--json") == 0
    assert _json(capsys) == {"rows": [], "count": 0, "truncated": False,
                             "row_cap": 5000}
    assert sv(world, "db", "trials", "--from", "yesterday") == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_the_query_reads_from_three_sources(tmp_path, monkeypatch,
                                            capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    sql = "SELECT player, p FROM revealed_trials ORDER BY player"
    assert sv(world, "db", "query", sql) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].split() == ["player", "p"]
    assert "bru" in out and "1 rows" in out

    file = tmp_path / "query.sql"
    file.write_text(sql, encoding="utf-8")
    assert sv(world, "db", "query", "--file", str(file), "--json") == 0
    value = _json(capsys)
    assert value["columns"] == ["player", "p"]
    assert [row[0] for row in value["rows"]] == ["bru"]

    monkeypatch.setattr("sys.stdin", io.StringIO(sql))
    assert sv(world, "db", "query", "-", "--csv") == 0
    assert capsys.readouterr().out.startswith("player,p\r\nbru,")

    for argv in (("db", "query"), ("db", "query", sql, "--file", str(file)),
                 ("db", "query", sql, "--csv", "--json"),
                 ("db", "query", "--file", str(tmp_path / "none.sql"))):
        assert sv(world, *argv) == 1
        assert "refused:" in capsys.readouterr().err


def test_the_query_stays_read_only_and_keeps_its_limits(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for sql in ("DELETE FROM trials", "PRAGMA query_only = OFF",
                "SELECT 1; DELETE FROM trials"):
        assert sv(world, "db", "query", sql) == 1
        assert "refused:" in capsys.readouterr().err
    many = ("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n "
            "WHERE i < 1500) SELECT i FROM n")
    assert sv(world, "db", "query", many, "--json") == 0
    value = _json(capsys)
    assert len(value["rows"]) == 1000 and value["truncated"] is True


def test_the_query_writes_its_answer_to_a_new_file(tmp_path, monkeypatch,
                                                   capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    store.set_account_description(world.root, "bru", "two\nlines",
                                  timestamp=FIXED_CLOCK)
    sql = "SELECT player, description FROM accounts"
    out = tmp_path / "answer.csv"
    assert sv(world, "db", "query", sql, "--csv", "--out", str(out)) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "wrote 1 rows" in captured.err
    # A file gets the cell as it is, and a terminal gets a code.
    assert out.read_bytes() == b'player,description\r\nbru,"two\nlines"\r\n'
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    assert sv(world, "db", "query", sql, "--csv") == 0
    assert 'bru,two\\nlines\r\n' in capsys.readouterr().out
    assert sv(world, "db", "query", sql, "--csv", stdout_is_tty=False) == 0
    assert 'bru,"two\nlines"\r\n' in capsys.readouterr().out

    assert sv(world, "db", "query", sql, "--csv", "--out", str(out)) == 1
    assert "is there" in capsys.readouterr().err
    assert sv(world, "db", "query", sql, "--out",
              str(tmp_path / "no-folder" / "answer.txt")) == 1
    assert "cannot write" in capsys.readouterr().err


# ---- the journal reader ----


def _entry(world, entry_id: str, phase: str, at: str, command: str,
           **more) -> None:
    values = {"player": None, "day": None, "facts": {}, "error_kind": None,
              "outcome": "done" if phase == "end" else None, **more}
    store.write_operator_entry(world.root, store.OperatorEntry(
        entry_id=entry_id, phase=phase, at=at, login=LOGIN,
        login_source="sudo-user", command=command, **values))


def test_the_log_prints_one_line_for_each_command(tmp_path, monkeypatch,
                                                  capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "log") == 0
    assert capsys.readouterr().out == "no journal entry\n"

    _entry(world, "a" * 16, "start", "2026-08-11T10:00:00+00:00",
           "players revoke", player="bru")
    _entry(world, "a" * 16, "end", "2026-08-11T10:00:01+00:00",
           "players revoke", player="bru")
    _entry(world, "b" * 16, "start", "2026-08-12T09:00:00+00:00",
           "day close", day=OPEN_DAY)
    _entry(world, "c" * 16, "start", "2026-08-12T11:00:00+00:00",
           "players signout", player="ade")
    _entry(world, "c" * 16, "end", "2026-08-12T11:00:02+00:00",
           "players signout", player="ade", outcome="refused",
           facts={"ended": 0}, error_kind="StoreError")

    assert sv(world, "log") == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert "players revoke  player=bru  done" in lines[0]
    assert f"{LOGIN} (sudo-user)" in lines[0]
    # A start with no end: the outcome of the command is not known.
    assert f"day close  day={OPEN_DAY}  outcome not recorded" in lines[1]
    assert "refused  ended=0  error=StoreError" in lines[2]

    for flags, count in ((("--player", "bru"), 1), (("--day", OPEN_DAY), 1),
                         (("--command", "players signout"), 1),
                         (("--since", "2026-08-12"), 2),
                         (("--since", "2026-08-12T10:00:00+00:00"), 1),
                         (("--limit", "2"), 2),
                         (("--player", "ade", "--day", OPEN_DAY), 0)):
        assert sv(world, "log", *flags, "--json") == 0
        entries = _json(capsys)["entries"]
        assert len({entry["entry_id"] for entry in entries}) == count, flags
    assert sv(world, "log", "--limit", "1") == 0
    assert "players signout" in capsys.readouterr().out

    for flags in (("--since", "last week"), ("--limit", "0")):
        assert sv(world, "log", *flags) == 1
        assert "refused:" in capsys.readouterr().err


def test_a_read_writes_no_journal_record(tmp_path, monkeypatch,
                                         capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for command in (("status",), ("days",), ("day", "show"),
                    ("day", "send", OPEN_DAY, "ade"), ("schedule",),
                    ("players", "list"), ("players", "show", "ade"),
                    ("players", "history", "ade"), ("db", "status"),
                    ("db", "trials"), ("log",),
                    ("db", "query", "SELECT 1"), ("db", "verify")):
        assert sv(world, *command) == 0, command
    capsys.readouterr()
    assert world.journal() == ()
    assert not store.operator_journal_dir(world.root).exists()


# ---- the refusals of each command ----


def test_a_user_that_is_not_the_store_owner_is_refused(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    owner = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    for command in (("status",), ("players", "list"), ("log",)):
        assert sv(world, *command) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "belongs to a different user" in captured.err
        assert "sudo sv" in captured.err


def test_a_store_that_is_not_there_is_refused(tmp_path, monkeypatch,
                                              capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    world.path = config_file(tmp_path, world.config, name="no-store.json",
                             store_root=str(tmp_path / "nowhere"))
    assert sv(world, "status") == 1
    captured = capsys.readouterr()
    assert "there is no store folder" in captured.err
    assert "sudo sv" in captured.err
    assert not (tmp_path / "nowhere").exists()


def test_a_base_address_that_is_not_loopback_is_refused(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for address in ("http://example.com:8000", "https://127.0.0.1:8000",
                    "http://10.0.0.5:8000"):
        assert sv(world, "status", "--base-url", address) == 1
        assert "loopback" in capsys.readouterr().err
    assert world.sent == []


def test_a_bad_config_and_a_bad_login_are_refused(tmp_path, monkeypatch,
                                                  capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert operator_cli.main(
        ["--service-config", str(tmp_path / "none.json"), "status"]) == 1
    assert "cannot read config" in capsys.readouterr().err
    assert sv(world, "status", environ={plan.LOGIN_VARIABLE: "opal"}) == 1
    assert plan.LOGIN_SOURCE_VARIABLE in capsys.readouterr().err


def test_the_flags_work_before_and_after_the_command(tmp_path, monkeypatch,
                                                     capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert operator_cli.main(
        ["--json", "days", "--service-config", str(world.path)],
        call=world.call, environ={}, now=world.clock) == 0
    assert len(_json(capsys)["days"]) == 2
    with pytest.raises(SystemExit) as stop:
        sv(world, "days", "--nope")
    assert stop.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_a_transport_error_of_a_read_is_not_an_error(tmp_path, monkeypatch,
                                                     capsys) -> None:
    world = build_world(tmp_path, monkeypatch)

    def silent(_method, _path, _body, _timeout):
        raise rollover.TransportError("connection refused")

    assert sv(world, "status", "--json", call=silent) == 0
    assert _json(capsys)["server_answers"] is False
