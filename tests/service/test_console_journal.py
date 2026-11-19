"""The operator journal that the server writes (spec OC1 section 13).

Each console path that changes the store writes a `start` record and an
`end` record, with the fixed name of the console. A day move that the
operator command sent names the record of the command, and the server
writes no second one.
"""

import pytest
from test_console_paths import (FIRST_DAY, HEADERS, HOUR, OPEN_DAY, PNG,
                                _strand_the_open_day, _world)

from service import access, operator_plan, store

MARKER = "a red barn ABCD-EFGH (private)"


def _journal(fixture) -> tuple[store.OperatorEntry, ...]:
    return store.list_operator_entries(fixture["store"])


def _pairs(fixture, command: str) -> list[tuple[store.OperatorEntry,
                                                store.OperatorEntry]]:
    """The `start` and `end` records of each command of this name."""
    records = [entry for entry in _journal(fixture)
               if entry.command == command]
    assert [entry.phase for entry in records] == \
        ["start", "end"] * (len(records) // 2), command
    pairs = list(zip(records[::2], records[1::2], strict=True))
    for start, end in pairs:
        assert start.entry_id == end.entry_id
        assert (start.login, start.login_source) \
            == (end.login, end.login_source)
    return pairs


def _journal_bytes(fixture) -> bytes:
    folder = store.operator_journal_dir(fixture["store"])
    if not folder.is_dir():
        return b""
    return b"".join(path.read_bytes() for path in sorted(folder.iterdir()))


def _one(fixture, command: str):
    pairs = _pairs(fixture, command)
    assert len(pairs) == 1, command
    return pairs[0]


def test_each_player_change_of_the_console_goes_in_the_journal(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, clock = _world(tmp_path, monkeypatch)
    for name in ("ade", "bru"):
        access.open_session(fixture["store"], name, user_agent="Firefox",
                            instant=clock.instant)
    sessions = client.get("/api/dev/players/ade",
                          headers=HEADERS).json()["sessions"]
    session_id = sessions[0]["id"]

    code = client.post("/api/dev/players/ade/recovery-code",
                       headers=HEADERS).json()["recovery_code"]
    client.put("/api/dev/players/ade/description", headers=HEADERS,
               json={"description": MARKER})
    client.put("/api/dev/players/ade/avatar", headers=HEADERS, content=PNG)
    client.delete("/api/dev/players/ade/avatar", headers=HEADERS)
    client.delete(f"/api/dev/players/ade/sessions/{session_id}",
                  headers=HEADERS)
    client.post("/api/dev/players/bru/signout", headers=HEADERS)
    client.post("/api/dev/players/bru/revoke", headers=HEADERS)
    client.post("/api/dev/players/bru/restore", headers=HEADERS)
    client.post("/api/dev/prune", headers=HEADERS)
    client.post("/api/dev/index/build", headers=HEADERS)
    client.post("/api/dev/players/bru/delete", headers=HEADERS,
                json={"confirm": "bru"})

    expected = {
        "players recovery-code": ("ade", {}),
        "players describe": ("ade", {"field": "description"}),
        "players avatar-set": ("ade", {"field": "avatar"}),
        "players avatar-clear": ("ade", {"field": "avatar"}),
        "players revoke": ("bru", {}),
        "players restore": ("bru", {}),
        "players delete": ("bru", {}),
        "db build": (None, {}),
    }
    for command, (player, facts) in expected.items():
        start, end = _one(fixture, command)
        assert (start.login, start.login_source) \
            == ("console", "operator-token"), command
        assert start.player == end.player == player, command
        assert end.outcome == "done" and end.error_kind is None, command
        assert dict(end.facts) == facts, command
        # The name is a command of the operator command too, thus the
        # journal reader finds the two tools by one name.
        operator_plan.command_for(tuple(command.split()))

    # The clock of this world does not move, thus the two entries sort
    # by their identifiers. The player tells them apart.
    signouts = {start.player: end
                for start, end in _pairs(fixture, "players signout")}
    assert dict(signouts["ade"].facts) == {"session": session_id[:12],
                                           "ended": 1}
    assert dict(signouts["bru"].facts) == {"ended": 1}
    _start, pruned = _one(fixture, "players prune")
    assert set(pruned.facts) == {"sessions", "device_codes"}

    # No code and no text of a person is in a journal file.
    raw = _journal_bytes(fixture)
    assert code.encode() not in raw
    assert code.replace("-", "").encode() not in raw
    assert MARKER.encode() not in raw and b"red barn" not in raw


def test_the_day_moves_of_the_console_go_in_the_journal(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    closed = client.post("/api/day/close", headers=HEADERS)
    assert closed.status_code == 200
    start, end = _one(fixture, "day close")
    assert start.login == "console" and start.day == end.day == OPEN_DAY
    assert dict(end.facts) == {"trial_rows": 1, "quarantined": 0}

    assert client.post("/api/day/reveal", headers=HEADERS).status_code == 200
    start, end = _one(fixture, "day reveal")
    assert start.day == OPEN_DAY and end.outcome == "done"

    opened = client.post("/api/day/open", headers=HEADERS).json()["day"]
    start, end = _one(fixture, "day open")
    # An open learns its day from the move.
    assert start.day is None and end.day == opened


def test_a_named_day_move_of_the_console_goes_in_the_journal(
        tmp_path, monkeypatch) -> None:
    fixture, config, client, _clock = _world(tmp_path, monkeypatch)
    stranded, _newer = _strand_the_open_day(fixture, config)
    answer = client.post("/api/dev/day/reveal", headers=HEADERS,
                         json={"day": stranded})
    assert answer.status_code == 200
    start, end = _one(fixture, "day reveal")
    assert start.day == end.day == stranded and end.outcome == "done"


def test_the_pause_and_the_run_go_in_the_journal(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(
        tmp_path, monkeypatch, hour=HOUR, instant="2026-08-12T22:30:00")
    client.post("/api/dev/rollover/pause", headers=HEADERS,
                json={"paused": True, "note": MARKER})
    _start, paused = _one(fixture, "schedule pause")
    assert dict(paused.facts) == {"paused": True}
    client.post("/api/dev/rollover/pause", headers=HEADERS,
                json={"paused": False})
    _start, resumed = _one(fixture, "schedule resume")
    assert dict(resumed.facts) == {"paused": False}

    answer = client.post("/api/dev/rollover/run", headers=HEADERS).json()
    assert answer["run"]["steps"] == ["close", "reveal", "open"]
    start, end = _one(fixture, "schedule run")
    assert dict(start.facts) == {"retries": 0}
    assert dict(end.facts) == {"steps": ("close", "reveal", "open"),
                               "retries": 0}
    # The run is one entry: its steps get no entry of their own.
    names = {entry.command for entry in _journal(fixture)}
    assert names == {"schedule pause", "schedule resume", "schedule run"}
    # The note of the pause is in the control record, and not here.
    assert MARKER.encode() not in _journal_bytes(fixture)


def test_a_refused_change_has_its_cause_and_no_words(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    client.post("/api/dev/players/bru/revoke", headers=HEADERS)
    refused = client.post("/api/dev/players/bru/recovery-code",
                          headers=HEADERS)
    assert refused.status_code == 409
    _start, end = _one(fixture, "players recovery-code")
    assert end.outcome == "refused"
    assert end.error_kind == "http-409:refused"
    assert dict(end.facts) == {}
    detail = refused.json()["detail"]
    assert detail.encode() not in _journal_bytes(fixture)

    bad = client.post("/api/dev/players/ade/delete", headers=HEADERS,
                      json={"confirm": "not-the-name"})
    assert bad.status_code == 409
    _start, end = _one(fixture, "players delete")
    assert end.outcome == "refused" and end.player == "ade"
    assert store.read_player_or_none(fixture["store"], "ade") is not None


def test_a_caller_with_no_token_and_a_read_get_no_record(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    wrong = {"Authorization": "Bearer not-the-token"}
    for method, path, body in (
            ("POST", "/api/dev/players/ade/revoke", None),
            ("POST", "/api/day/close", None),
            ("POST", "/api/dev/prune", None),
            ("PUT", "/api/dev/players/ade/description",
             {"description": "x"})):
        answer = client.request(method, path, headers=wrong, json=body)
        assert answer.status_code in (401, 404)
    for path in ("/api/dev/days", "/api/dev/players",
                 "/api/dev/players/ade", "/api/dev/schedule",
                 f"/api/dev/day?day={OPEN_DAY}", "/api/dev/index",
                 "/api/dev/players/ade/deletion"):
        assert client.get(path, headers=HEADERS).status_code == 200
    # A name that is not stored stops before the journal too.
    assert client.post("/api/dev/players/nobody/revoke",
                       headers=HEADERS).status_code == 404
    assert _journal(fixture) == ()


def test_the_rank_of_a_day_that_is_not_revealed_goes_in_the_journal(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    # A revealed day shows its target to each reader: no record.
    shown = client.get(f"/api/dev/rankings?day={FIRST_DAY}&player=bru",
                       headers=HEADERS)
    assert shown.status_code == 200
    assert _journal(fixture) == ()

    blind = client.get(f"/api/dev/rankings?day={OPEN_DAY}&player=ade",
                       headers=HEADERS)
    assert blind.status_code == 200
    start, end = _one(fixture, "day rank")
    assert (start.player, start.day) == ("ade", OPEN_DAY)
    assert dict(start.facts) == {"shows_target": True}
    assert end.outcome == "done" and start.login == "console"

    # A send that is not stored stops before the journal.
    assert client.get(f"/api/dev/rankings?day={OPEN_DAY}&player=bru",
                      headers=HEADERS).status_code == 404
    assert len(_pairs(fixture, "day rank")) == 1


def test_a_change_with_no_start_record_does_not_start(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)

    def refuse(_root, _entry) -> None:
        raise store.StoreError("the journal folder is not there")

    monkeypatch.setattr(store, "write_operator_entry", refuse)
    for method, path, body in (
            ("POST", "/api/dev/players/bru/revoke", None),
            ("POST", "/api/day/close", None),
            ("PUT", "/api/dev/players/ade/description",
             {"description": "changed"})):
        answer = client.request(method, path, headers=HEADERS, json=body)
        assert answer.status_code == 500, path
        assert answer.json()["cause"] == "journal"
    root = fixture["store"]
    assert store.read_player_or_none(root, "bru").status == "active"
    assert store.read_day_record(root, OPEN_DAY).status == "open"
    account = store.read_account_or_none(root, "ade")
    assert account is None or account.description == ""


def test_a_change_with_no_end_record_completes_and_shows_no_outcome(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch)
    write = store.write_operator_entry

    def start_alone(root, entry) -> None:
        if entry.phase == "end":
            raise OSError("the disk is full")
        write(root, entry)

    monkeypatch.setattr(store, "write_operator_entry", start_alone)
    answer = client.post("/api/dev/players/bru/revoke", headers=HEADERS)
    assert answer.status_code == 200
    assert store.read_player_or_none(fixture["store"],
                                     "bru").status == "revoked"
    records = _journal(fixture)
    assert [(entry.command, entry.phase) for entry in records] \
        == [("players revoke", "start")]


def test_the_public_process_writes_a_record_for_a_caller_with_the_token(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch,
                                              dev_mode=False)
    assert client.post("/api/day/close", headers=HEADERS).status_code == 200
    start, end = _one(fixture, "day close")
    # No dev mode: the caller is not the console. The record says what
    # the server knows, that the caller held the token.
    assert (start.login, start.login_source) \
        == ("token-holder", "operator-token")
    assert end.day == OPEN_DAY and end.outcome == "done"


@pytest.mark.parametrize("made", ["0123456789abcdef", "not-hex", ""])
def test_a_made_identifier_does_not_skip_the_journal(
        tmp_path, monkeypatch, made: str) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch,
                                              dev_mode=False)
    answer = client.post("/api/day/close", headers=HEADERS,
                         json={"day": OPEN_DAY, "journal_entry": made})
    assert answer.status_code == 200
    # No `start` record has that identifier, thus the server writes
    # its own two records.
    start, _end = _one(fixture, "day close")
    assert start.login == "token-holder" and start.entry_id != made


def test_the_record_of_a_different_move_does_not_skip_the_journal(
        tmp_path, monkeypatch) -> None:
    fixture, _config, client, _clock = _world(tmp_path, monkeypatch,
                                              dev_mode=False)
    root = fixture["store"]
    # A stored `start` record, of a command that is not this move.
    store.write_operator_entry(root, store.OperatorEntry(
        entry_id="00000000000000aa", phase="start",
        at="2026-08-12T12:00:00+00:00", login="opal",
        login_source="sudo-user", command="players revoke", player="bru",
        day=None, outcome=None, facts={}, error_kind=None))
    client.post("/api/day/close", headers=HEADERS,
                json={"day": OPEN_DAY,
                      "journal_entry": "00000000000000aa"})
    start, _end = _one(fixture, "day close")
    assert start.login == "token-holder"
