"""Integration: the target, the rank, the quarantine, and the module
commands of the operator command (spec OC1 sections 3.3 and 3.4,
rulings D2, D7, and D8, build item OC1.7).

The terminal shows no target and no rank of a day that is open or
closing. A closed day shows them with `--show-target`, a question, and
a journal entry. The last test is the marker test of spec OC1 section
9: no journal file holds a text that a person wrote.
"""

import json
import stat

import pytest
from sv_world import (FIRST_DAY, HOUR, LOGIN, OPEN_DAY, TOKEN, build_vp1_world,
                      build_world, send, sv)
from svc_fixture import FIXED_CLOCK, mixed_wire_record

from pool.artifacts import load_image_bytes
from providers.fake.text_encoder import REFUSAL_MARKER
from service import auth, index, operator_cli, store
from service import operator_plan as plan
from service.day import close_day

MARKER = "zebra-marker"

# Legal arguments for each command of the table.
SAMPLES = {
    ("status",): [], ("days",): [], ("day", "show"): [],
    ("day", "send"): [OPEN_DAY, "ade"], ("schedule",): [],
    ("players", "list"): [], ("players", "show"): ["ade"],
    ("players", "history"): ["ade"],
    ("players", "avatar"): ["ade", "--save", "a.png"],
    ("db", "status"): [], ("db", "verify"): [],
    ("db", "query"): ["SELECT 1"], ("db", "trials"): [], ("log",): [],
    ("day", "open"): [], ("day", "close"): [OPEN_DAY],
    ("day", "reveal"): [], ("day", "quarantine"): [OPEN_DAY, "ade",
                                                   "--note", "n"],
    ("schedule", "pause"): ["--note", "n"], ("schedule", "resume"): [],
    ("schedule", "run"): [], ("players", "recovery-code"): ["ade"],
    ("players", "restore"): ["ade", "--code-to-pipe"],
    ("players", "revoke"): ["ade"],
    ("players", "signout"): ["ade", "--session", "abcdef"],
    ("players", "describe"): ["ade", "--clear"],
    ("players", "avatar-set"): ["ade", "--file", "a.png"],
    ("players", "avatar-clear"): ["ade"],
    ("players", "delete"): ["ade", "--confirm", "ade"],
    ("players", "prune"): [], ("players", "claim-names"): [],
    ("db", "build"): [], ("day", "target"): ["--show-target"],
    ("day", "rank"): [OPEN_DAY, "ade", "--limit", "5"],
    ("day", "rescore"): ["--config", "c.json"], ("day", "migrate"): [],
    ("day", "day-scores"): ["--date", OPEN_DAY],
    ("db", "export"): ["--out", "o"], ("public",): ["withheld"],
    ("rollup", "assemble"): [], ("pool-keys", "make"): [],
}


def _pair(world, command: str):
    """The `start` record and the `end` record of the one command of
    this name in the journal."""
    records = [entry for entry in world.journal() if entry.command == command]
    assert [entry.phase for entry in records] == ["start", "end"], command
    start, end = records
    assert start.entry_id == end.entry_id and start.login == LOGIN
    return start, end


def _target(world, day: str) -> str:
    return store.read_day_record(world.root, day).target_id


def _closing(world) -> None:
    store.update_day_status(world.root, OPEN_DAY, expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)


# ---- the command table and the argument tree ----


def test_each_command_of_the_table_has_a_parser_and_a_handler() -> None:
    assert set(SAMPLES) == {command.path for command in plan.COMMANDS}
    parser = operator_cli._parser()
    for command in plan.COMMANDS:
        args, unread = parser.parse_known_args(
            [*command.path, *SAMPLES[command.path]])
        assert operator_cli._path_of(args) == command.path
        # The tree reads each word of a command that is not a module
        # command, and no word of a module command.
        expected = SAMPLES[command.path] if command.kind == "module" else []
        assert unread == expected, command.path
        assert callable(operator_cli._handler_for(command))


# ---- the target ----


def test_the_target_of_a_revealed_day_prints_with_no_question(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    shown = _target(world, FIRST_DAY)
    assert sv(world, "day", "target", FIRST_DAY) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith(f"target {shown}\ncredit Test photo")
    assert "page https://commons.wikimedia.org/wiki/File:" in captured.out
    assert sv(world, "day", "target", FIRST_DAY, "--show-target",
              "--json") == 0
    value = json.loads(capsys.readouterr().out)
    assert value["target_id"] == shown and value["status"] == "revealed"
    assert value["credit"]["source"] == "Wikimedia Commons"
    assert world.prompts == [] and world.journal() == ()

    saved = tmp_path / "target.png"
    assert sv(world, "day", "target", FIRST_DAY, "--save", str(saved)) == 0
    assert f"wrote the image to {saved}" in capsys.readouterr().out
    assert saved.read_bytes() == load_image_bytes(world.fixture["data"],
                                                  shown)
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    # A path that is there refuses, and the file stays as it was.
    saved.write_bytes(b"mine")
    assert sv(world, "day", "target", FIRST_DAY, "--save", str(saved)) == 1
    assert "is there" in capsys.readouterr().err
    assert saved.read_bytes() == b"mine"


def test_the_target_and_the_rank_of_an_open_day_refuse_with_each_flag(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    hidden = _target(world, OPEN_DAY)
    for status in ("open", "closing"):
        for argv in (("day", "target"), ("day", "target", OPEN_DAY),
                     ("day", "rank", OPEN_DAY, "ade")):
            for flags in ((), ("--show-target",), ("--show-target", "--yes"),
                          ("--json",)):
                assert sv(world, *argv, *flags) == 1, (status, argv, flags)
                captured = capsys.readouterr()
                assert captured.out == ""
                assert "open or closing" in captured.err
                assert "Spec S1 R3" in captured.err
                assert "No flag changes this" in captured.err
                assert hidden not in captured.err
        if status == "open":
            _closing(world)
    assert world.prompts == [] and world.journal() == ()


def test_a_closed_day_shows_its_target_with_the_flag_and_a_record(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    close_day(world.config, clock=lambda: FIXED_CLOCK)
    hidden = _target(world, OPEN_DAY)

    # With no flag the command says which flag shows the target.
    assert sv(world, "day", "target") == 1
    captured = capsys.readouterr()
    assert "--show-target" in captured.err and hidden not in captured.err
    # The flag asks a question, and nothing answers it here.
    assert sv(world, "day", "target", "--show-target",
              stdin_is_tty=False) == 1
    assert "the standard input is not a terminal" in capsys.readouterr().err
    world.answer = "no"
    assert sv(world, "day", "target", "--show-target") == 1
    captured = capsys.readouterr()
    assert f"{OPEN_DAY} is closed and not revealed." in captured.err
    assert "ends a blind view" in captured.err
    assert hidden not in captured.out + captured.err
    assert world.journal() == ()

    world.answer = "yes"
    saved = tmp_path / "closed.png"
    assert sv(world, "day", "target", "--show-target", "--save",
              str(saved)) == 0
    captured = capsys.readouterr()
    assert f"target {hidden}" in captured.out
    assert saved.read_bytes() == load_image_bytes(world.fixture["data"],
                                                  hidden)
    # A read with a journal entry: it ends a blind view of the day.
    start, end = _pair(world, "day target")
    assert start.day == end.day == OPEN_DAY and start.player is None
    assert start.facts == end.facts == {"shows_target": True}
    assert end.outcome == "done"

    assert sv(world, "day", "target", OPEN_DAY, "--show-target", "--yes",
              "--json", stdin_is_tty=False) == 0
    assert json.loads(capsys.readouterr().out)["target_id"] == hidden
    assert len(world.journal()) == 4


def test_a_vp1_day_before_its_close_has_no_target_to_show(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_vp1_world(tmp_path, monkeypatch,
                            instant="2026-08-12T12:00:00")
    for flags in ((), ("--show-target",)):
        assert sv(world, "day", "target", *flags) == 0
        captured = capsys.readouterr()
        assert captured.out == "no target until the close\n"
        assert "hidden" not in captured.out + captured.err
    assert sv(world, "day", "target", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {
        "day": OPEN_DAY, "status": "open", "target_visibility": "none-yet"}
    for argv in (("day", "rank", OPEN_DAY, "ade"),
                 ("day", "rank", OPEN_DAY, "ade", "--show-target"),
                 ("day", "target", "--save", str(tmp_path / "none.png"))):
        assert sv(world, *argv) == 1
        assert "no target until the close" in capsys.readouterr().err
    assert world.prompts == [] and world.journal() == ()


# ---- the rank ----


def test_the_rank_of_a_revealed_day_scores_the_stored_send(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    stored = store.read_json_or_none(
        store.trial_row_path(world.root, FIRST_DAY, "bru"))
    shown = _target(world, FIRST_DAY)
    assert sv(world, "day", "rank", FIRST_DAY, "bru", "--json") == 0
    value = json.loads(capsys.readouterr().out)
    # The command scores the stored record again, thus the trial agrees
    # with the stored row.
    assert value["trial"]["p"] == stored["p"]
    assert len(value["rankings"]) == len(world.fixture["image_ids"])
    marked = [row for row in value["rankings"] if row["is_target"]]
    assert [row["image_id"] for row in marked] == [shown]

    assert sv(world, "day", "rank", FIRST_DAY, "bru", "--limit", "3") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith(f"p={stored['p']}  rank=")
    assert lines[1] == (f"target position {value['target_position']} of "
                        f"{len(world.fixture['image_ids'])}")
    starred = [line for line in lines if line.startswith("*")]
    assert len(starred) == 1 and starred[0].endswith(shown)
    assert any(line.startswith("atom: ") for line in lines)
    assert world.prompts == [] and world.journal() == ()

    for argv, text in (
            (("day", "rank", FIRST_DAY, "ade"), "ade has no stored send"),
            (("day", "rank", "2026-01-01", "ade"), "no stored day"),
            (("day", "rank", FIRST_DAY, "bru", "--limit", "0"), "--limit"),
            (("day", "target", "2026-01-01"), "no stored day")):
        assert sv(world, *argv) == 1
        assert text in capsys.readouterr().err


def test_the_rank_of_a_closed_day_wants_the_flag_and_writes_a_record(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    close_day(world.config, clock=lambda: FIXED_CLOCK)
    stored = store.read_json_or_none(
        store.trial_row_path(world.root, OPEN_DAY, "ade"))
    assert sv(world, "day", "rank", OPEN_DAY, "ade") == 1
    assert "--show-target" in capsys.readouterr().err
    assert world.journal() == ()

    assert sv(world, "day", "rank", OPEN_DAY, "ade", "--show-target") == 0
    captured = capsys.readouterr()
    assert "ends a blind view" in captured.err
    assert f"p={stored['p']}" in captured.out
    start, end = _pair(world, "day rank")
    assert start.day == OPEN_DAY and start.player == "ade"
    assert end.facts == {"shows_target": True} and end.outcome == "done"


# ---- the quarantine ----


def _held_day(world) -> None:
    """A day in `closing` with one send that the provider refuses."""
    record = {**mixed_wire_record(),
              "impressions": [f"{REFUSAL_MARKER} {MARKER} words", "cold air"]}
    send(world, OPEN_DAY, "bru", record)
    _closing(world)


def test_quarantine_skips_a_send_that_the_provider_refuses(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    _held_day(world)
    note = f"{MARKER} the provider refuses this text"
    assert sv(world, "day", "quarantine", OPEN_DAY, "bru", "--note",
              note, stdin_is_tty=False) == 1
    assert "the standard input is not a terminal" in capsys.readouterr().err
    assert store.list_quarantined(world.root, OPEN_DAY) == ()

    assert sv(world, "day", "quarantine", OPEN_DAY, "bru", "--note",
              note) == 0
    captured = capsys.readouterr()
    assert f"Skip the send of bru on {OPEN_DAY}?" in captured.err
    assert "the send of bru is quarantined - close the day again" \
        in captured.out
    record = store.read_quarantine_or_none(world.root, OPEN_DAY, "bru")
    assert record.decided_by == "operator" and record.note == note
    start, end = _pair(world, "day quarantine")
    assert start.day == OPEN_DAY and start.player == "bru"
    assert start.facts == {} and end.facts == {"quarantined": 1}
    assert end.outcome == "done"

    # A send that scores is not skipped: a recorded refusal.
    assert sv(world, "day", "quarantine", OPEN_DAY, "ade", "--note",
              note, "--yes") == 1
    assert "scores in the blind run" in capsys.readouterr().err
    last = world.journal()[-1]
    assert (last.player, last.outcome, last.error_kind) \
        == ("ade", "refused", "StoreError")
    assert store.list_quarantined(world.root, OPEN_DAY) == ("bru",)

    # The close of the server continues with the other send.
    assert sv(world, "day", "close") == 0
    assert "trial_rows=1  quarantined=1" in capsys.readouterr().out
    folder = store.operator_journal_dir(world.root)
    for path in folder.iterdir():
        assert MARKER.encode() not in path.read_bytes()


def test_quarantine_wants_a_day_that_a_close_holds(tmp_path, monkeypatch,
                                                   capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "day", "quarantine", OPEN_DAY, "ade", "--note", "x") == 1
    assert "'closing'" in capsys.readouterr().err
    _start, end = _pair(world, "day quarantine")
    assert (end.outcome, end.error_kind) == ("refused", "StoreError")
    assert sv(world, "day", "quarantine", "2026-01-01", "ade", "--note",
              "x") == 1
    assert "no stored day" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        sv(world, "day", "quarantine", OPEN_DAY, "ade")
    capsys.readouterr()
    assert len(world.journal()) == 2


# ---- the module commands ----


@pytest.mark.parametrize("words, module, expected", [
    (("day", "rescore", "--config", "c.json", "--from", FIRST_DAY),
     "service.day", ["rescore", "--config", "c.json", "--from", FIRST_DAY]),
    (("day", "migrate"), "service.day", ["migrate"]),
    (("day", "day-scores", "--date", OPEN_DAY), "service.day",
     ["day-scores", "--date", OPEN_DAY]),
    (("db", "export", "--out", "o", "--format", "jsonl"), "service.index",
     ["export", "--out", "o", "--format", "jsonl"]),
    (("public", "withhold", OPEN_DAY, "ade", "--note", "a note"),
     "service.public", ["withhold", OPEN_DAY, "ade", "--note", "a note"]),
    (("rollup", "assemble", "--scoring-config-hash", "abc"),
     "service.rollup", ["assemble", "--scoring-config-hash", "abc"]),
    (("pool-keys", "make"), "service.pool_keys", ["make"]),
])
def test_a_module_command_gets_the_arguments_with_no_change(
        tmp_path, monkeypatch, capsys, words, module, expected) -> None:
    import importlib

    world = build_world(tmp_path, monkeypatch)
    got: list[list[str]] = []

    def entry(argv: list[str]) -> int:
        got.append(argv)
        return 7

    monkeypatch.setattr(importlib.import_module(module), "main", entry)
    # The exit code of the module is the exit code of the command.
    assert sv(world, *words) == 7
    assert got == [["--service-config", str(world.path), *expected]]
    # A module command prints text: --json refuses at each position.
    assert sv(world, "--json", *words) == 1
    assert sv(world, *words, "--json") == 1
    assert capsys.readouterr().err.count("--json does not work") == 2
    assert len(got) == 1 and world.journal() == ()


def test_the_module_commands_do_their_work(tmp_path, monkeypatch,
                                           capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "day", "migrate") == 0
    assert capsys.readouterr().out == "migrate days=2 backfilled=0\n"
    out = tmp_path / "export"
    assert sv(world, "db", "export", "--out", str(out), "--salt", "s") == 0
    assert "exported trials=1" in capsys.readouterr().out
    assert (out / "trials.csv").is_file()
    assert sv(world, "public", "withheld") == 0
    capsys.readouterr()
    # The refusal of a module is its own line and its own exit code.
    assert sv(world, "day", "day-scores", "--date", OPEN_DAY) == 1
    assert "refused:" in capsys.readouterr().err
    assert index.index_path(world.fixture["data"]).is_file()
    assert world.journal() == ()


def test_a_module_command_obeys_the_store_owner_rule(tmp_path, monkeypatch,
                                                     capsys) -> None:
    import os

    world = build_world(tmp_path, monkeypatch)
    owner = os.geteuid()
    monkeypatch.setattr(os, "geteuid", lambda: owner + 1)
    assert sv(world, "day", "migrate") == 1
    assert "belongs to a different user" in capsys.readouterr().err


# ---- the marker test of spec OC1 section 9 ----


def test_no_journal_file_holds_a_text_that_a_person_wrote(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch, hour=HOUR)
    _held_day(world)
    text_file = tmp_path / "description.txt"
    text_file.write_text(f"{MARKER} from a file\n", encoding="utf-8")
    steps = (
        (0, ("players", "describe", "bru", "--text", f"{MARKER} text")),
        (0, ("players", "describe", "ade", "--text-file", str(text_file))),
        (0, ("schedule", "pause", "--note", f"{MARKER} pause note")),
        (0, ("schedule", "resume")),
        (0, ("day", "send", OPEN_DAY, "bru")),
        (0, ("day", "quarantine", OPEN_DAY, "bru", "--note",
             f"{MARKER} quarantine note")),
        (1, ("day", "quarantine", OPEN_DAY, "ade", "--note",
             f"{MARKER} second note")),
        (0, ("day", "close")),
        (0, ("day", "rank", OPEN_DAY, "ade", "--show-target")),
        (0, ("day", "target", "--show-target")),
        (0, ("db", "query", f"SELECT '{MARKER}' AS text")),
        (1, ("db", "query", f"DELETE FROM players WHERE '{MARKER}'")),
        (0, ("players", "revoke", "bru")),
        (1, ("players", "recovery-code", "bru")),
        (0, ("players", "restore", "bru")),
        (0, ("players", "recovery-code", "ade")),
        (0, ("log",)),
    )
    codes = []
    for expected, argv in steps:
        assert sv(world, *argv) == expected, argv
        out = capsys.readouterr().out
        if "recovery code " in out:
            codes.append(out.split("recovery code ")[1].split("\n")[0])
    assert len(codes) == 2
    secrets = [MARKER, TOKEN, REFUSAL_MARKER]
    for code in codes:
        secrets += [code, auth.normalize_recovery_code(code),
                    auth.recovery_code_hash(
                        auth.normalize_recovery_code(code))]

    files = sorted(store.operator_journal_dir(world.root).iterdir())
    # Two records for each of the 13 commands that write the journal.
    assert len(files) == 26
    for path in files:
        raw = path.read_bytes()
        for secret in secrets:
            assert secret.encode() not in raw, (path.name, secret)
        record = json.loads(raw)
        assert set(record["facts"]) <= set(plan.FACT_KEYS)
        assert record["login"] == LOGIN
