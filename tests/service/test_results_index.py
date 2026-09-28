"""Integration: the results index and its two readers (spec BR1 section 5).

The index is a copy of the store that a build makes again at each
moment. Trial rows enter for revealed days alone and a day's target
stays NULL until its reveal (I7). The operator reads it through a
gated endpoint, a research export replaces each player name with a
salted digest, and a player downloads their own data from the store.
"""

import ast
import csv
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, build_service_fixture,
                         mixed_wire_record, pinned_session_value,
                         plant_session)

from service import auth, index, players, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

REPO = Path(__file__).resolve().parents[2]
FIRST, SECOND = "2026-08-12", "2026-08-13"
OPERATOR = "test-operator-token"
HEADERS = {"Authorization": f"Bearer {OPERATOR}"}
ADE, BRU = f"ade.{'1' * 43}", f"bru.{'2' * 43}"


def _send(root: Path, day: str, player: str, trial_id: str) -> None:
    store.write_once_json(
        store.submission_path(root, day, player),
        {"day": day, "player": player, "trial_id": trial_id,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})


def _world(tmp_path):
    """Two players. The first day revealed with two rows, the second
    day open with one send."""
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    root = fixture["store"]
    for token, label in ((ADE, "Ade"), (BRU, "Bru Lin")):
        name, secret = auth.parse_token(token)
        players.mint_player(config, player=name, display_name=label,
                            clock=lambda: FIXED_CLOCK, secret=secret)
        plant_session(root, token)
    open_day(config, date=FIRST, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    _send(root, FIRST, "ade", "a" * 32)
    _send(root, FIRST, "bru", "b" * 32)
    close_day(config, clock=lambda: FIXED_CLOCK)
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    open_day(config, date=SECOND, clock=lambda: FIXED_CLOCK,
             pick_seed="c" * 32, secret="d" * 64)
    _send(root, SECOND, "ade", "c" * 32)
    target = index.index_path(fixture["data"])
    return fixture, root, target


def _query(target: Path, sql: str) -> list[tuple]:
    connection = index.connect(target)
    try:
        return [tuple(row) for row in connection.execute(sql)]
    finally:
        connection.close()


def test_the_build_copies_the_store_and_holds_back_the_open_day(
        tmp_path) -> None:
    _fixture, root, target = _world(tmp_path)
    index.build(root, target)
    assert _query(target, "SELECT player, display_name, status FROM "
                          "players ORDER BY player") \
        == [("ade", "Ade", "active"), ("bru", "Bru Lin", "active")]
    days = _query(target, "SELECT day, status, target_id IS NULL, "
                          "secret IS NULL FROM days ORDER BY day")
    assert days == [(FIRST, "revealed", 0, 0), (SECOND, "open", 1, 1)]
    assert _query(target, "SELECT day, player, stroke_count, "
                          "impression_count FROM submissions "
                          "ORDER BY day, player") \
        == [(FIRST, "ade", 2, 2), (FIRST, "bru", 2, 2), (SECOND, "ade", 2, 2)]
    # I7: rows for the revealed day alone.
    assert _query(target, "SELECT DISTINCT day FROM trials") == [(FIRST,)]
    stored = store.read_json_or_none(store.trial_row_path(root, FIRST, "ade"))
    (row,) = _query(target, "SELECT p, target_rank, decoy_count, pinned "
                            "FROM trials WHERE player = 'ade'")
    assert row == (stored["p"], stored["target_rank"],
                   stored["decoy_count"], 1)
    atoms = _query(target, "SELECT atom_text FROM trial_atoms WHERE "
                           "player = 'ade' ORDER BY position")
    assert [text for (text,) in atoms] \
        == [atom["atom_text"] for atom in stored["report"]]
    # No credential enters the index.
    text = target.read_bytes()
    for credential in (b"token_hash", b"1" * 43, b"2" * 43):
        assert credential not in text


def test_a_closed_day_holds_no_row_until_its_reveal(tmp_path) -> None:
    fixture, root, target = _world(tmp_path)
    config = fixture["service_config"]
    close_day(config, clock=lambda: FIXED_CLOCK)
    index.build(root, target)
    assert _query(target, "SELECT DISTINCT day FROM trials") == [(FIRST,)]
    assert _query(target, f"SELECT target_id IS NULL FROM days WHERE day = "
                          f"'{SECOND}'") == [(1,)]
    reveal_day(config, clock=lambda: FIXED_CLOCK)
    index.ensure_current(root, target)
    assert _query(target, "SELECT DISTINCT day FROM trials ORDER BY day") \
        == [(FIRST,), (SECOND,)]


def test_a_rescore_row_enters_unpinned(tmp_path) -> None:
    _fixture, root, target = _world(tmp_path)
    stored = store.read_json_or_none(store.trial_row_path(root, FIRST, "ade"))
    sibling = {**stored, "scoring_config_hash": "f" * 64, "p": 0.25}
    store.write_once_json(store.trial_row_path(root, FIRST, "ade", "ffffffff"),
                          sibling)
    index.build(root, target)
    assert _query(target, "SELECT pinned, p FROM trials WHERE player = "
                          "'ade' ORDER BY pinned") \
        == [(0, 0.25), (1, stored["p"])]
    # The view reads the pinned row alone.
    assert _query(target, "SELECT count(*) FROM revealed_trials WHERE "
                          "player = 'ade'") == [(1,)]


def test_a_store_write_makes_the_index_stale(tmp_path) -> None:
    _fixture, root, target = _world(tmp_path)
    first = index.build(root, target)
    assert index.read_fingerprint(target) == first
    assert index.verify(root, target) == []
    _send(root, SECOND, "bru", "d" * 32)
    assert index.store_fingerprint(root) != first
    problems = index.verify(root, target)
    assert problems == ["submissions: 1 rows missing from the index, "
                        "0 rows the store does not hold"]
    index.ensure_current(root, target)
    assert index.verify(root, target) == []
    # The build leaves no temporary file.
    assert sorted(path.name for path in target.parent.iterdir()) \
        == [target.name]


def test_ensure_current_builds_once_for_an_unchanged_store(tmp_path) -> None:
    _fixture, root, target = _world(tmp_path)
    index.ensure_current(root, target)
    before = target.stat().st_mtime_ns
    index.ensure_current(root, target)
    assert target.stat().st_mtime_ns == before


def test_the_index_is_read_only_to_its_readers(tmp_path) -> None:
    _fixture, root, target = _world(tmp_path)
    index.build(root, target)
    connection = index.connect(target)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM players")
    finally:
        connection.close()


def test_the_export_names_no_player(tmp_path) -> None:
    _fixture, root, target = _world(tmp_path)
    index.build(root, target)
    with pytest.raises(index.ResultsIndexError, match="salt"):
        index.export(target, tmp_path / "out", salt="", file_format="csv")
    counts = index.export(target, tmp_path / "csv", salt="s3cret",
                          file_format="csv")
    assert counts == {"trials": 2, "trial_atoms": counts["trial_atoms"],
                      "submissions": 2}
    assert counts["trial_atoms"] > 0
    with (tmp_path / "csv" / "trials.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["day"] for row in rows} == {FIRST}
    assert {row["player"] for row in rows} \
        == {index.pseudonym("ade", "s3cret"), index.pseudonym("bru", "s3cret")}
    for path in (tmp_path / "csv").iterdir():
        text = path.read_text(encoding="utf-8")
        for name in ("ade", "bru", "Bru Lin"):
            assert f'"{name}"' not in text and f",{name}," not in text
    # A different salt gives different names, and the same salt the
    # same names.
    assert index.pseudonym("ade", "s3cret") != index.pseudonym("ade", "x")
    index.export(target, tmp_path / "jsonl", salt="s3cret",
                 file_format="jsonl")
    lines = (tmp_path / "jsonl" / "submissions.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert {json.loads(line)["day"] for line in lines} == {FIRST}


def _client(fixture) -> TestClient:
    return TestClient(create_app(fixture["service_config"],
                                 operator_token=OPERATOR),
                      base_url="https://testserver")


def test_the_operator_endpoint_serves_revealed_rows(tmp_path) -> None:
    fixture, root, target = _world(tmp_path)
    client = _client(fixture)
    assert client.get("/api/ops/trials").status_code == 401
    client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(ADE))
    assert client.get("/api/ops/trials").status_code == 401
    answer = client.get("/api/ops/trials", headers=HEADERS)
    assert answer.status_code == 200
    body = answer.json()
    assert body["count"] == 2
    assert {(row["day"], row["player"], row["display_name"])
            for row in body["rows"]} \
        == {(FIRST, "ade", "Ade"), (FIRST, "bru", "Bru Lin")}
    assert all(row["target_id"] for row in body["rows"])
    one = client.get("/api/ops/trials?player=bru&from=2026-08-01&to="
                     "2026-08-12", headers=HEADERS).json()
    assert [row["player"] for row in one["rows"]] == ["bru"]
    none = client.get("/api/ops/trials?from=2026-08-13", headers=HEADERS)
    assert none.json() == {"rows": [], "count": 0}
    assert client.get("/api/ops/trials?from=nope",
                      headers=HEADERS).status_code == 400
    assert client.get("/api/ops/trials?player=../x",
                      headers=HEADERS).status_code == 400
    # The endpoint built the index on its first use.
    assert target.is_file()


def test_the_player_export_is_the_callers_own(tmp_path) -> None:
    fixture, _root, _target = _world(tmp_path)
    client = _client(fixture)
    assert client.get("/api/me/export").status_code == 401
    client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(ADE))
    answer = client.get("/api/me/export")
    assert answer.status_code == 200
    assert answer.headers["content-disposition"].startswith(
        'attachment; filename="starvector-ade-')
    body = answer.json()
    assert body["player"] == "ade" and body["display_name"] == "Ade"
    assert [day["day"] for day in body["days"]] == [FIRST, SECOND]
    revealed, open_day_row = body["days"]
    assert revealed["result"]["p"] is not None
    assert revealed["target_id"] is not None
    assert revealed["submission"]["record"] == mixed_wire_record()
    # The open day: the player's own send, and no score and no target.
    assert open_day_row["status"] == "open"
    assert open_day_row["result"] is None
    assert open_day_row["target_id"] is None
    assert "bru" not in answer.text and "Bru Lin" not in answer.text


def test_the_player_export_reads_the_store_alone(tmp_path) -> None:
    fixture, root, target = _world(tmp_path)

    def snapshot() -> dict:
        return {str(path): path.read_bytes() for path in root.rglob("*")
                if path.is_file()}

    before = snapshot()
    client = _client(fixture)
    client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(BRU))
    assert client.get("/api/me/export").status_code == 200
    assert snapshot() == before
    assert not target.exists()


def test_the_command_line_builds_verifies_and_exports(tmp_path,
                                                      capsys) -> None:
    fixture, root, target = _world(tmp_path)
    config = fixture["service_config"]
    path = tmp_path / "service.json"
    path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port}), encoding="utf-8")
    arguments = ["--service-config", str(path)]
    assert index.main([*arguments, "verify"]) == 1
    assert index.main([*arguments, "build"]) == 0
    assert index.main([*arguments, "verify"]) == 0
    assert index.main([*arguments, "path"]) == 0
    assert str(target) in capsys.readouterr().out
    assert index.main([*arguments, "export", "--out",
                       str(tmp_path / "research"), "--salt", "abc"]) == 0
    assert (tmp_path / "research" / "trials.csv").is_file()
    assert root.is_dir()


_FIT_SIDE = ("core", "pipeline", "pool", "providers", "validation")


def test_no_fit_side_module_imports_the_service() -> None:
    """I6: nothing that fits, validates, or prepares can read the
    results index or the trial store through the server package."""
    offenders = []
    for package in _FIT_SIDE:
        for path in sorted((REPO / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name == "service" or name.startswith("service."):
                        offenders.append(
                            f"{path.relative_to(REPO)} imports {name}")
    assert offenders == []
