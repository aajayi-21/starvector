"""Integration: the player commands of the operator command (spec OC1
sections 3.2, 6, and 7, build item OC1.5).

Each command that changes the store asks its question, then writes a
`start` record and an `end` record of the journal. The tests read the
two records of each command, and each refusal that comes before them.
"""

import datetime
import json

import pytest
from sv_world import FIRST_DAY, LOGIN, build_world, sv
from svc_fixture import FIXED_CLOCK

from service import access, auth, index, players, signin, store

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 24
MARKER = "zebra-marker-text"


def _pair(world, command: str):
    """The `start` record and the `end` record of the one command of
    this name in the journal."""
    records = [entry for entry in world.journal() if entry.command == command]
    assert [entry.phase for entry in records] == ["start", "end"], command
    start, end = records
    assert start.entry_id == end.entry_id
    assert start.login == end.login == LOGIN
    assert start.login_source == end.login_source == "sudo-user"
    assert start.outcome is None
    return start, end


def _printed_code(out: str) -> str:
    return out.split("recovery code ")[1].split("\n")[0]


def _journal_bytes(world) -> bytes:
    folder = store.operator_journal_dir(world.root)
    return b"".join(path.read_bytes() for path in sorted(folder.iterdir()))


# ---- the recovery code ----


def test_the_recovery_code_prints_one_time_after_the_question(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "players", "recovery-code", "ade") == 0
    captured = capsys.readouterr()
    assert "Make a recovery code for ade?" in captured.err
    assert "24 hours" in captured.err
    assert world.prompts == ["Type yes to continue: "]
    code = _printed_code(captured.out)
    assert auth.normalize_recovery_code(code) is not None
    assert captured.out.count(code) == 1 and code not in captured.err
    hold = datetime.timedelta(hours=24)
    usable_at = (world.clock.instant + hold).isoformat()
    assert f"it works from {usable_at}" in captured.out
    assert signin.operator_code_view(world.root, "ade")["usable_at"] \
        == usable_at

    start, end = _pair(world, "players recovery-code")
    assert start.player == end.player == "ade" and end.outcome == "done"
    assert start.facts == {} and end.facts == {} and end.error_kind is None
    raw = _journal_bytes(world)
    assert code.encode() not in raw
    assert auth.normalize_recovery_code(code).encode() not in raw


def test_a_code_to_a_pipe_refuses_before_the_code_is_made(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for flags in ((), ("--json",), ("--yes",)):
        assert sv(world, "players", "recovery-code", "ade", *flags,
                  stdout_is_tty=False) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "--code-to-pipe" in captured.err
        assert "No code was made" in captured.err
    # No question, no code in the slot of the operator, and no record.
    assert world.prompts == []
    assert signin.operator_code_view(world.root, "ade") is None
    assert store.read_credential_or_none(world.root, "ade") is None
    assert world.journal() == ()

    players.revoke_player(world.config, player="bru")
    assert sv(world, "players", "restore", "bru", stdout_is_tty=False) == 1
    capsys.readouterr()
    assert store.read_player_record(world.root, "bru").status == "revoked"

    # The flag sends the code to the pipe, as text and as JSON.
    assert sv(world, "players", "recovery-code", "ade", "--code-to-pipe",
              "--json", "--yes", stdout_is_tty=False) == 0
    value = json.loads(capsys.readouterr().out)
    assert auth.normalize_recovery_code(value["recovery_code"]) is not None
    assert value["player"] == "ade"


def test_a_code_for_a_revoked_player_is_a_recorded_refusal(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    players.revoke_player(world.config, player="bru")
    assert sv(world, "players", "recovery-code", "bru") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "refused: player 'bru' is revoked" in captured.err
    start, end = _pair(world, "players recovery-code")
    assert end.outcome == "refused" and end.error_kind == "StoreError"
    assert end.player == "bru" and end.facts == {}
    # The journal holds the type of the error and not its message.
    assert b"a recovery code is" not in _journal_bytes(world)
    assert signin.operator_code_view(world.root, "bru") is None


def test_restore_makes_the_account_active_with_a_code(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    players.revoke_player(world.config, player="bru")
    assert sv(world, "players", "restore", "bru") == 0
    captured = capsys.readouterr()
    assert "Restore bru?" in captured.err
    assert "player bru active" in captured.out
    code = _printed_code(captured.out)
    assert auth.normalize_recovery_code(code) is not None
    assert store.read_player_record(world.root, "bru").status == "active"
    _start, end = _pair(world, "players restore")
    assert end.outcome == "done" and end.player == "bru"
    assert code.encode() not in _journal_bytes(world)

    # The command is for a revoked player: an active one refuses.
    assert sv(world, "players", "restore", "ade", "--json") == 1
    assert "refused:" in capsys.readouterr().err
    refused = [entry for entry in world.journal()
               if entry.player == "ade" and entry.phase == "end"]
    assert [entry.outcome for entry in refused] == ["refused"]


# ---- revoke and sign-out ----


def test_revoke_asks_and_records(tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    access.open_session(world.root, "bru", user_agent="Firefox",
                        instant=world.clock.instant)
    assert sv(world, "players", "revoke", "bru", "--json") == 0
    captured = capsys.readouterr()
    assert "Revoke bru?" in captured.err
    assert json.loads(captured.out) == {"player": "bru", "status": "revoked"}
    assert store.read_player_record(world.root, "bru").status == "revoked"
    assert store.list_sessions(world.root, "bru") == ()
    start, end = _pair(world, "players revoke")
    assert start.player == "bru" and end.outcome == "done"
    assert start.at == end.at == world.clock.instant.isoformat()


def test_signout_ends_each_device_or_one(tmp_path, monkeypatch,
                                         capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for _ in range(3):
        access.open_session(world.root, "ade", user_agent="Firefox",
                            instant=world.clock.instant)
    ids = [digest for digest, _record in store.list_sessions(world.root,
                                                             "ade")]
    # One session: no question, as in the console.
    assert sv(world, "players", "signout", "ade", "--session",
              ids[0][:10]) == 0
    captured = capsys.readouterr()
    assert "player ade sessions ended: 1" in captured.out
    assert world.prompts == []
    left = [digest for digest, _record in store.list_sessions(world.root,
                                                              "ade")]
    assert sorted(left) == sorted(ids[1:])
    start, end = _pair(world, "players signout")
    assert start.facts == {"session": ids[0][:12]}
    assert end.facts == {"session": ids[0][:12], "ended": 1}
    assert end.outcome == "done" and end.player == "ade"

    # A short start, a start of no session, and the session that ended.
    for prefix, text in (("abc", "first 6 characters"),
                         ("0" * 64, "no live session"),
                         (ids[0][:10], "no live session")):
        assert sv(world, "players", "signout", "ade", "--session",
                  prefix) == 1
        assert text in capsys.readouterr().err
    assert len(world.journal()) == 2

    assert sv(world, "players", "signout", "ade") == 0
    captured = capsys.readouterr()
    assert "Sign ade out on every device?" in captured.err
    assert "sessions ended: 2" in captured.out
    assert store.list_sessions(world.root, "ade") == ()
    ends = [entry for entry in world.journal() if entry.phase == "end"]
    assert ends[-1].facts == {"ended": 2}


# ---- the questions ----


def test_no_terminal_and_no_yes_refuses_before_a_change(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for command in (("players", "revoke", "bru"),
                    ("players", "signout", "ade"),
                    ("players", "recovery-code", "ade")):
        assert sv(world, *command, stdin_is_tty=False) == 1, command
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "the standard input is not a terminal" in captured.err
        assert "--yes" in captured.err and "Nothing changed" in captured.err
    assert world.prompts == [] and world.journal() == ()
    assert store.read_player_record(world.root, "bru").status == "active"

    # The flag answers for a script, and nothing reads the input.
    assert sv(world, "players", "revoke", "bru", "--yes",
              stdin_is_tty=False) == 0
    captured = capsys.readouterr()
    assert world.prompts == [] and "Revoke bru?" not in captured.err
    assert store.read_player_record(world.root, "bru").status == "revoked"


def test_an_answer_that_is_not_yes_changes_and_records_nothing(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    for answer in ("no", "y", "", "yes please"):
        world.answer = answer
        assert sv(world, "players", "revoke", "bru") == 1
        captured = capsys.readouterr()
        assert "Revoke bru?" in captured.err
        assert "the answer was not yes" in captured.err
    assert store.read_player_record(world.root, "bru").status == "active"
    assert world.journal() == ()

    world.answer = " YES "
    assert sv(world, "players", "revoke", "bru") == 0
    assert store.read_player_record(world.root, "bru").status == "revoked"

    def no_input(_prompt: str) -> str:
        raise EOFError

    assert sv(world, "players", "revoke", "ade", ask=no_input) == 1
    assert store.read_player_record(world.root, "ade").status == "active"


# ---- moderation ----


def test_describe_sets_and_clears_with_no_text_in_the_journal(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "players", "describe", "bru", "--text",
              f"hello {MARKER}") == 0
    captured = capsys.readouterr()
    assert captured.out == "player bru: description set\n"
    assert captured.err == "" and world.prompts == []
    assert store.read_account_or_none(world.root, "bru").description \
        == f"hello {MARKER}"
    start, end = _pair(world, "players describe")
    assert start.facts == end.facts == {"field": "description"}
    assert end.outcome == "done" and end.player == "bru"
    assert MARKER.encode() not in _journal_bytes(world)

    file = tmp_path / "text.txt"
    file.write_text(f"from a file {MARKER}\n", encoding="utf-8")
    assert sv(world, "players", "describe", "bru", "--text-file",
              str(file), "--json") == 0
    assert json.loads(capsys.readouterr().out)["description"] \
        == f"from a file {MARKER}"
    assert sv(world, "players", "describe", "bru", "--clear") == 0
    assert "description cleared" in capsys.readouterr().out
    assert store.read_account_or_none(world.root, "bru").description == ""
    assert MARKER.encode() not in _journal_bytes(world)
    assert len(world.journal()) == 6

    # An illegal text and a name with no record stop before the journal.
    for argv in (("bru", "--text", "x" * 501), ("bru", "--text", " lead"),
                 ("nobody", "--text", "hello"),
                 ("bru", "--text-file", str(tmp_path / "none.txt"))):
        assert sv(world, "players", "describe", *argv) == 1
        assert "refused:" in capsys.readouterr().err
    assert len(world.journal()) == 6
    with pytest.raises(SystemExit):
        sv(world, "players", "describe", "bru")
    with pytest.raises(SystemExit):
        sv(world, "players", "describe", "bru", "--text", "a", "--clear")
    capsys.readouterr()


def test_the_avatar_commands_replace_and_remove(tmp_path, monkeypatch,
                                                capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    picture = tmp_path / "new.png"
    picture.write_bytes(PNG)
    assert sv(world, "players", "avatar-set", "ade", "--file",
              str(picture)) == 0
    assert "player ade: avatar set" in capsys.readouterr().out
    assert store.read_avatar_or_none(world.root, "ade") == PNG
    start, end = _pair(world, "players avatar-set")
    assert start.facts == end.facts == {"field": "avatar"}
    assert end.outcome == "done" and end.player == "ade"

    assert sv(world, "players", "avatar-clear", "ade", "--json") == 0
    assert json.loads(capsys.readouterr().out) \
        == {"player": "ade", "avatar_hash": None}
    assert store.read_avatar_or_none(world.root, "ade") is None
    _start, end = _pair(world, "players avatar-clear")
    assert end.facts == {"field": "avatar"} and end.outcome == "done"

    # Bytes that are not a picture: the store refuses, with a record.
    picture.write_bytes(b"not a picture")
    assert sv(world, "players", "avatar-set", "bru", "--file",
              str(picture)) == 1
    assert "refused:" in capsys.readouterr().err
    ends = [entry for entry in world.journal()
            if entry.player == "bru" and entry.phase == "end"]
    assert [(entry.outcome, entry.error_kind) for entry in ends] \
        == [("refused", "StoreError")]


# ---- the deletion ----


def test_delete_shows_the_preview_then_wants_the_typed_name(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "players", "delete", "bru") == 0
    out = capsys.readouterr().out
    assert "preview: deleting bru removes" in out
    assert f"days played 1 (one send each), {FIRST_DAY} to {FIRST_DAY}" in out
    assert "To delete, run again with --confirm bru" in out
    assert sv(world, "players", "delete", "bru", "--json") == 0
    assert json.loads(capsys.readouterr().out)["days_played"] == 1
    # The preview is a read: no question and no record.
    assert world.prompts == [] and world.journal() == ()

    # A typed name that does not agree, with --yes too, deletes nothing.
    for flags in (("--confirm", "ade"), ("--confirm", "Bru"),
                  ("--confirm", "ade", "--yes"), ("--confirm", "")):
        assert sv(world, "players", "delete", "bru", *flags) == 1
        assert "--confirm does not equal the name 'bru'" \
            in capsys.readouterr().err
    assert sv(world, "players", "delete", "bru", "--yes") == 0
    assert "nothing changed" in capsys.readouterr().out
    assert store.read_player_or_none(world.root, "bru") is not None
    assert world.journal() == ()

    assert sv(world, "players", "delete", "bru", "--confirm", "bru",
              stdin_is_tty=False) == 0
    out = capsys.readouterr().out
    assert "player bru deleted - the earlier results show as anon-" in out
    assert store.read_player_or_none(world.root, "bru") is None
    # The journal keeps the username of a deleted player.
    start, end = _pair(world, "players delete")
    assert start.player == end.player == "bru" and end.outcome == "done"
    assert sv(world, "players", "delete", "bru", "--confirm", "bru") == 1
    assert "no stored player 'bru'" in capsys.readouterr().err


# ---- prune, the name claims, and the index ----


def test_prune_and_claim_names_record_their_counts(tmp_path, monkeypatch,
                                                   capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    old = world.clock.instant - datetime.timedelta(days=400)
    access.open_session(world.root, "ade", user_agent="Firefox", instant=old)
    access.issue_device_code(world.root, "ade", old)
    access.open_session(world.root, "ade", user_agent="Firefox",
                        instant=world.clock.instant)
    assert sv(world, "players", "prune") == 0
    assert capsys.readouterr().out == "pruned sessions=1 device_codes=1\n"
    assert len(store.list_sessions(world.root, "ade")) == 1
    _start, end = _pair(world, "players prune")
    assert end.facts == {"sessions": 1, "device_codes": 1}
    assert end.player is None and end.day is None

    assert sv(world, "players", "claim-names") == 0
    assert "claimed 2 name(s): ade, bru" in capsys.readouterr().out
    _start, end = _pair(world, "players claim-names")
    assert end.outcome == "done" and end.facts == {}
    assert sv(world, "players", "claim-names", "--json") == 0
    assert json.loads(capsys.readouterr().out) == {"claimed": []}

    # Two stored names with one folded shape: a recorded refusal.
    players.make_player(world.config, player="a-de",
                        clock=lambda: FIXED_CLOCK)
    assert sv(world, "players", "claim-names") == 1
    assert "folded shape" in capsys.readouterr().err
    last = world.journal()[-1]
    assert (last.phase, last.outcome, last.error_kind) \
        == ("end", "refused", "StoreError")


def test_db_build_makes_the_index_again_with_a_record(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    target = index.index_path(world.fixture["data"])
    target.unlink()
    assert sv(world, "db", "build") == 0
    out = capsys.readouterr().out
    assert "exists yes" in out and "current yes" in out
    assert target.is_file() and world.prompts == []
    _start, end = _pair(world, "db build")
    assert end.outcome == "done" and end.facts == {}
    assert sv(world, "db", "verify") == 0
    capsys.readouterr()


# ---- the journal writes ----


def test_a_start_record_that_does_not_write_stops_the_change(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)

    def broken(_root, _entry):
        raise OSError("disk full")

    monkeypatch.setattr(store, "write_operator_entry", broken)
    for command in (("players", "revoke", "bru"),
                    ("players", "describe", "bru", "--text", "hello"),
                    ("players", "delete", "bru", "--confirm", "bru"),
                    ("players", "recovery-code", "ade")):
        assert sv(world, *command) == 1, command
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "the start record of the journal could not be written" \
            in captured.err
        assert "Nothing changed" in captured.err
    assert store.read_player_record(world.root, "bru").status == "active"
    assert store.read_account_or_none(world.root, "bru") is None
    assert signin.operator_code_view(world.root, "ade") is None


def test_a_change_with_no_end_record_gives_the_exit_code_3(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)
    write = store.write_operator_entry

    def no_end(root, entry):
        if entry.phase == "end":
            raise store.StoreError("the disk refuses the end record")
        write(root, entry)

    monkeypatch.setattr(store, "write_operator_entry", no_end)
    assert sv(world, "players", "recovery-code", "ade") == 3
    captured = capsys.readouterr()
    # The change completed: the code prints, because no second run can
    # print it again.
    assert auth.normalize_recovery_code(_printed_code(captured.out))
    assert "the change completed" in captured.err
    assert signin.operator_code_view(world.root, "ade") is not None
    assert [entry.phase for entry in world.journal()] == ["start"]

    # A refused change with no end record is a refusal, with a line.
    players.revoke_player(world.config, player="bru")
    assert sv(world, "players", "recovery-code", "bru") == 1
    assert "the end record of the journal could not be written" \
        in capsys.readouterr().err

    monkeypatch.setattr(store, "write_operator_entry", write)
    assert sv(world, "log") == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert all("outcome not recorded" in line for line in lines)


def test_an_error_that_is_not_known_records_a_failure_and_continues(
        tmp_path, monkeypatch, capsys) -> None:
    world = build_world(tmp_path, monkeypatch)

    def broken(_config, *, player):
        raise RuntimeError(f"secret words of {player}: {MARKER}")

    monkeypatch.setattr(players, "revoke_player", broken)
    with pytest.raises(RuntimeError):
        sv(world, "players", "revoke", "bru")
    capsys.readouterr()
    _start, end = _pair(world, "players revoke")
    assert (end.outcome, end.error_kind) == ("failed", "RuntimeError")
    assert MARKER.encode() not in _journal_bytes(world)

    def bad_value(_config, *, player):
        raise ValueError(f"a value rule of {player}: {MARKER}")

    monkeypatch.setattr(players, "revoke_player", bad_value)
    assert sv(world, "players", "revoke", "ade") == 1
    assert f"failed: a value rule of ade: {MARKER}" \
        in capsys.readouterr().err
    last = world.journal()[-1]
    assert (last.outcome, last.error_kind) == ("failed", "ValueError")
    assert MARKER.encode() not in _journal_bytes(world)


def test_the_actor_is_the_user_of_the_process_with_no_script(
        tmp_path, monkeypatch, capsys) -> None:
    import os
    import pwd

    world = build_world(tmp_path, monkeypatch)
    assert sv(world, "players", "describe", "bru", "--text", "hi",
              environ={}) == 0
    capsys.readouterr()
    start, _end = world.journal()
    assert start.login == pwd.getpwuid(os.geteuid()).pw_name
    assert start.login_source == "effective-user"
    assert start.player == "bru" and start.day is None
