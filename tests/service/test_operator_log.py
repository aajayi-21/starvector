"""Unit: the records of the operator journal (spec OC1 section 7, D3).

Pure store tests on a temporary directory - no pool, no server. The
tests pin the shape of an entry, the sequence of the journal, and the
narrow rules that keep the text of a person out of an entry.
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from service import store

AT = "2026-11-19T12:00:00+00:00"
STAMP = "20261119T120000000000Z"
ENTRY_ID = "0123456789abcdef"
SENTINEL = "my secret code ABCD-EFGH"


def _start(**changes: object) -> store.OperatorEntry:
    base = store.OperatorEntry(
        entry_id=ENTRY_ID, phase="start", at=AT, login="ade",
        login_source="sudo-user", command="players revoke", player="mira",
        day=None, outcome=None, facts={}, error_kind=None)
    return replace(base, **changes)


def _end(**changes: object) -> store.OperatorEntry:
    return _start(**{"phase": "end", "outcome": "done", **changes})


def _root(tmp_path: Path) -> Path:
    return Path(tmp_path) / "store"


def _names(root: Path) -> list[str]:
    return sorted(entry.name
                  for entry in store.operator_journal_dir(root).iterdir())


def _only_file(root: Path) -> Path:
    (name,) = _names(root)
    return store.operator_journal_dir(root) / name


def _rewrite(path: Path, **changes: object) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(changes)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_the_journal_folder_is_in_the_store(tmp_path) -> None:
    root = _root(tmp_path)
    assert store.operator_journal_dir(root) == root / "operator-log"


def test_a_start_and_end_pair_reads_back_with_each_field(tmp_path) -> None:
    root = _root(tmp_path)
    start = _start(command="day close", player=None, day="2026-11-18",
                   facts={"shows_target": True})
    end = _end(
        at="2026-11-19T12:00:07.250000+00:00", command="day close",
        player="mira", day="2026-11-18", outcome="failed",
        facts={"steps": ("close", "reveal"), "trial_rows": 12,
               "quarantined": 0, "paused": False, "field": "description",
               "exit_code": 1, "session": "0a1b2c3d", "retries": 2},
        error_kind="http-409:refused")
    store.write_operator_entry(root, start)
    store.write_operator_entry(root, end)

    assert store.list_operator_entries(root) == (start, end)
    read = store.list_operator_entries(root)[1]
    assert read.facts["steps"] == ("close", "reveal")
    assert read.facts["paused"] is False
    assert read.facts["quarantined"] == 0
    assert read.facts["quarantined"] is not False
    assert read.outcome == "failed" and read.error_kind == "http-409:refused"
    assert store.list_operator_entries(root)[0].outcome is None


def test_the_file_name_is_the_instant_the_identifier_and_the_phase(
        tmp_path) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    store.write_operator_entry(root, _end())
    assert _names(root) == [f"{STAMP}-{ENTRY_ID}-0-start.json",
                            f"{STAMP}-{ENTRY_ID}-1-end.json"]


def test_the_stored_record_holds_the_version_and_a_json_array(
        tmp_path) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start(facts={"steps": ["open"]}))
    assert json.loads(_only_file(root).read_text(encoding="utf-8")) == {
        "journal_version": store.OPERATOR_JOURNAL_VERSION,
        "entry_id": ENTRY_ID, "phase": "start", "at": AT, "login": "ade",
        "login_source": "sudo-user", "command": "players revoke",
        "player": "mira", "day": None, "outcome": None,
        "facts": {"steps": ["open"]}, "error_kind": None}
    # A fact that goes in as an array comes back as a tuple.
    (read,) = store.list_operator_entries(root)
    assert read.facts == {"steps": ("open",)}


def test_the_journal_reads_oldest_first_and_start_before_end(
        tmp_path) -> None:
    root = _root(tmp_path)
    first, second = "aaaaaaaa", "bbbbbbbb"
    # The second command has its instants in a different zone: the name
    # uses UTC, thus 13:00:01 at +01:00 sorts as 12:00:01.
    entries = (
        _end(entry_id=second, at="2026-11-19T13:00:02+01:00"),
        _end(entry_id=first),
        _start(entry_id=second, at="2026-11-19T13:00:01+01:00"),
        _start(entry_id=first),
    )
    for entry in entries:
        store.write_operator_entry(root, entry)
    assert [(entry.entry_id, entry.phase)
            for entry in store.list_operator_entries(root)] == [
        (first, "start"), (first, "end"), (second, "start"), (second, "end")]


def test_a_second_write_of_the_same_record_refuses(tmp_path) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    with pytest.raises(store.StoreError, match="one-write"):
        store.write_operator_entry(root, _start())
    # The same instant, identifier, and phase with different contents
    # refuses also: the first record stays.
    with pytest.raises(store.StoreError, match="one-write"):
        store.write_operator_entry(root, _start(login="other"))
    assert store.list_operator_entries(root) == (_start(),)


def test_the_limits_of_each_rule_are_legal(tmp_path) -> None:
    root = _root(tmp_path)
    entry = _end(
        entry_id="0" * 32, login="A.b_c-" + "d" * 58,
        command="a" * 31 + " " + "b" * 32, player="a" * 64,
        day="2026-11-19", error_kind="E" * 80,
        facts={"field": "description", "session": "a" * 64, "steps": (),
               "sessions": 0})
    short = _start(entry_id="0" * 8, at="2026-11-19T12:00:01+00:00")
    store.write_operator_entry(root, entry)
    store.write_operator_entry(root, short)
    assert store.list_operator_entries(root) == (entry, short)


BAD_ENTRIES = {
    "unknown phase": _start(phase="middle"),
    "start with an outcome": _start(outcome="done"),
    "end with no outcome": _end(outcome=None),
    "end with an unknown outcome": _end(outcome="ok"),
    "unknown login source": _start(login_source="ssh"),
    "unknown fact key": _start(facts={"note": "x"}),
    "fact key that is not text": _start(facts={1: "x"}),
    "fact text with a line break": _start(facts={"field": "a\nb"}),
    "fact text with a quotation mark": _start(facts={"field": 'a"b'}),
    "fact text with a line break at the end": _start(facts={"field": "a\n"}),
    "fact text of 81 characters": _start(facts={"field": "a" * 81}),
    "fact that is a float": _start(facts={"retries": 1.5}),
    "fact that is None": _start(facts={"paused": None}),
    "fact that is a mapping": _start(facts={"steps": {"open": 1}}),
    "fact sequence with a number": _start(facts={"steps": ("open", 1)}),
    "fact sequence with bad text": _start(facts={"steps": ("open", "a;b")}),
    "fact sequence in a sequence": _start(facts={"steps": (("open",),)}),
    "facts that are not a mapping": _start(facts=(("steps", 1),)),
    "empty login": _start(login=""),
    "login with a space": _start(login="a b"),
    "login of 65 characters": _start(login="a" * 65),
    "login with a line break": _start(login="ade\n"),
    "login that is not text": _start(login=7),
    "empty command": _start(command=""),
    "command with a capital": _start(command="Players revoke"),
    "command with two spaces": _start(command="players  revoke"),
    "command with a space first": _start(command=" players"),
    "command with a space last": _start(command="players "),
    "command with an underscore": _start(command="players_revoke"),
    "command of 65 characters": _start(command="a" * 65),
    "entry_id of 7 characters": _start(entry_id="0123abc"),
    "entry_id of 33 characters": _start(entry_id="0" * 33),
    "entry_id with capitals": _start(entry_id="0123ABCD"),
    "entry_id that is not hex": _start(entry_id="0123abcg"),
    "day with one digit": _start(day="2026-11-9"),
    "day that is a word": _start(day="today"),
    "player with a capital": _start(player="Mira"),
    "player with a space": _start(player="a b"),
    "empty error_kind": _end(error_kind=""),
    "error_kind with a space": _end(error_kind="Store Error"),
    "error_kind of 81 characters": _end(error_kind="x" * 81),
    "error_kind with a line break": _end(error_kind="StoreError\n"),
    "instant with no zone": _start(at="2026-11-19T12:00:00"),
    "instant that is a word": _start(at="noon"),
    "empty instant": _start(at=""),
    "instant that is not text": _start(at=None),
}


@pytest.mark.parametrize("label", sorted(BAD_ENTRIES))
def test_each_rule_refuses_at_the_write(tmp_path, label: str) -> None:
    root = _root(tmp_path)
    with pytest.raises(store.StoreError):
        store.write_operator_entry(root, BAD_ENTRIES[label])
    # A refused entry writes nothing, not the folder and not the store.
    assert not root.exists()
    assert store.list_operator_entries(root) == ()


def test_no_folder_and_an_empty_folder_are_an_empty_journal(tmp_path) -> None:
    root = _root(tmp_path)
    assert store.list_operator_entries(root) == ()
    store.operator_journal_dir(root).mkdir(parents=True)
    assert store.list_operator_entries(root) == ()


@pytest.mark.parametrize("version", [2, 0, "1", True, None, 1.0])
def test_an_unknown_journal_version_refuses_at_the_read(tmp_path,
                                                        version) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    path = _only_file(root)
    _rewrite(path, journal_version=version)
    with pytest.raises(store.StoreError, match="journal version") as caught:
        store.list_operator_entries(root)
    assert path.name in str(caught.value)


def test_a_record_with_no_version_refuses_at_the_read(tmp_path) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    path = _only_file(root)
    value = json.loads(path.read_text(encoding="utf-8"))
    del value["journal_version"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(store.StoreError, match="journal version"):
        store.list_operator_entries(root)


@pytest.mark.parametrize("text", ["{not json", "", "[1, 2]", '"text"'])
def test_a_file_that_is_not_a_json_object_refuses_and_is_named(
        tmp_path, text: str) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    bad = store.operator_journal_dir(root) / f"{STAMP}-ffffffff-0-start.json"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(store.StoreError) as caught:
        store.list_operator_entries(root)
    assert bad.name in str(caught.value)


@pytest.mark.parametrize("changes", [
    {"extra": 1},
    {"facts": ["steps"]},
    {"facts": {"note": "x"}},
    {"facts": {"field": "a\nb"}},
    {"facts": {"steps": [["open"]]}},
    {"phase": "end"},
    {"outcome": "done"},
    {"login": "a b"},
    {"at": "2026-11-19T12:00:00"},
    {"error_kind": "an error message"},
])
def test_a_stored_record_that_breaks_a_rule_refuses_and_is_named(
        tmp_path, changes: dict) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    path = _only_file(root)
    _rewrite(path, **changes)
    with pytest.raises(store.StoreError) as caught:
        store.list_operator_entries(root)
    assert path.name in str(caught.value)


def test_a_stored_record_with_a_field_missing_refuses(tmp_path) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    path = _only_file(root)
    value = json.loads(path.read_text(encoding="utf-8"))
    del value["login_source"]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(store.StoreError, match="expected the fields"):
        store.list_operator_entries(root)


@pytest.mark.parametrize("name", [
    f"{STAMP}-{ENTRY_ID}-1-end.json",
    f"20251119T120000000000Z-{ENTRY_ID}-0-start.json",
    "notes.txt",
])
def test_a_file_name_that_does_not_agree_with_its_record_refuses(
        tmp_path, name: str) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    path = _only_file(root)
    path.rename(path.with_name(name))
    with pytest.raises(store.StoreError, match="file name") as caught:
        store.list_operator_entries(root)
    assert name in str(caught.value)


def test_a_folder_in_the_journal_refuses(tmp_path) -> None:
    root = _root(tmp_path)
    (store.operator_journal_dir(root) / "old").mkdir(parents=True)
    with pytest.raises(store.StoreError, match="old"):
        store.list_operator_entries(root)


def test_a_write_that_has_not_ended_is_not_an_entry(tmp_path) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start())
    half = store.operator_journal_dir(root) / (
        f"{STAMP}-{ENTRY_ID}-1-end.json.abc123.tmp")
    half.write_text("{", encoding="utf-8")
    assert store.list_operator_entries(root) == (_start(),)


def test_the_read_entry_does_not_change(tmp_path) -> None:
    root = _root(tmp_path)
    store.write_operator_entry(root, _start(facts={"ended": 3}))
    (read,) = store.list_operator_entries(root)
    with pytest.raises(TypeError):
        read.facts["ended"] = 4  # type: ignore[index]


# ---- the sentinel: text that a person wrote stays out ----

@pytest.mark.parametrize("field", [
    "entry_id", "phase", "at", "login", "login_source", "command", "player",
    "day", "outcome", "error_kind"])
def test_the_sentinel_refuses_in_each_string_field(tmp_path,
                                                   field: str) -> None:
    root = _root(tmp_path)
    with pytest.raises(store.StoreError):
        store.write_operator_entry(root, _end(**{field: SENTINEL}))
    assert not root.exists()


@pytest.mark.parametrize("key", [
    SENTINEL, "note", "code", "recovery_code", "description", "message",
    "error", "query", "text", "detail"])
def test_the_sentinel_refuses_below_each_key_that_is_not_a_fact(
        tmp_path, key: str) -> None:
    root = _root(tmp_path)
    with pytest.raises(store.StoreError) as caught:
        store.write_operator_entry(root, _end(facts={key: SENTINEL}))
    assert SENTINEL not in str(caught.value)
    assert not root.exists()


@pytest.mark.parametrize("text", [
    SENTINEL + "\n",
    f'"{SENTINEL}"',
    f"{SENTINEL}!",
    "StoreError: no stored player 'mira'",
    "the provider refused: (content policy) 'a red barn'",
    "I see a red barn; it is big.\nA road goes to it.",
    "SELECT player FROM trials WHERE day = '2026-11-18'",
    f"a note of more than 80 characters, with the code at the end: "
    f"{SENTINEL} {SENTINEL}",
])
@pytest.mark.parametrize("key", store.OPERATOR_FACT_KEYS)
def test_text_of_a_person_refuses_below_each_fact_key(tmp_path, key: str,
                                                      text: str) -> None:
    root = _root(tmp_path)
    for value in (text, (text,), ["done", text]):
        with pytest.raises(store.StoreError) as caught:
            store.write_operator_entry(root, _end(facts={key: value}))
        # The refusal does not show the refused text.
        assert text not in str(caught.value)
    assert not root.exists()


@pytest.mark.parametrize("text", [
    SENTINEL, "StoreError: no stored player", "an error message",
    "http 409", "StoreError\n", 'Store"Error'])
def test_text_of_a_person_refuses_as_the_error_type(tmp_path,
                                                    text: str) -> None:
    root = _root(tmp_path)
    with pytest.raises(store.StoreError) as caught:
        store.write_operator_entry(root, _end(error_kind=text))
    assert text not in str(caught.value)
    assert not root.exists()


@pytest.mark.parametrize("key", store.OPERATOR_FACT_KEYS)
def test_a_recovery_code_refuses_below_each_fact_key(tmp_path,
                                                     key: str) -> None:
    """No fact shape accepts a code or the sentinel.

    Each fact key has one shape: a count, a flag, a step name, a field
    name, or the digits of a session identifier. A recovery code in its
    groups of four has hyphens and capital letters, and no shape holds
    them.
    """
    root = _root(tmp_path)
    code = "ABCD-EFGH-JKLM-NPQR-STUV-WXYZ"
    for value in (SENTINEL, code, code.lower(), (code,), [SENTINEL]):
        with pytest.raises(store.StoreError) as caught:
            store.write_operator_entry(root, _end(facts={key: value}))
        assert str(value) not in str(caught.value)
    assert not root.exists()


@pytest.mark.parametrize("facts", [
    {"trial_rows": -1}, {"trial_rows": True}, {"ended": "3"},
    {"paused": 1}, {"agrees": "yes"}, {"steps": ("open", "wait")},
    {"steps": "open"}, {"field": "password"}, {"field": "a" * 80},
    {"session": "ABCDEF"}, {"session": "abc"}, {"session": "g" * 8},
    {"exit_code": 1.0},
])
def test_each_fact_key_has_one_shape(tmp_path, facts: dict) -> None:
    root = _root(tmp_path)
    with pytest.raises(store.StoreError):
        store.write_operator_entry(root, _end(facts=facts))
    assert not root.exists()


def test_each_legal_fact_shape_goes_in_and_comes_back(tmp_path) -> None:
    root = _root(tmp_path)
    entry = _end(facts={
        "steps": ("close", "reveal", "open"), "trial_rows": 0,
        "quarantined": 2, "ended": 3, "field": "avatar", "paused": False,
        "exit_code": 2, "session": "0123abcd", "sessions": 4,
        "device_codes": 1, "agrees": True, "shows_target": True,
        "retries": 0})
    store.write_operator_entry(root, entry)
    assert store.list_operator_entries(root) == (entry,)
