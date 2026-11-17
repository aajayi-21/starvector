"""Spec MD1: moderation and account deletion, through the server."""

import dataclasses
import datetime
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from svc_fixture import (FIXED_CLOCK, QuickDigester, build_service_fixture,
                         mint_player, mixed_wire_record, plant_session)

from service import auth, players, public, rollup, store
from service.day import close_day, open_day, reveal_day
from service.server import create_app

OPERATOR_TOKEN = "test-operator-token"
GOOD = "correct horse battery"
ORIGIN = {"origin": "https://testserver"}
OPERATOR = {**ORIGIN, "authorization": f"Bearer {OPERATOR_TOKEN}"}
PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


def _world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"], signup="open")
    app = create_app(config, dev_mode=True, operator_token=OPERATOR_TOKEN,
                     digester=QuickDigester(), usual_passwords=frozenset())
    return config, app


def _client(app, headers=ORIGIN) -> TestClient:
    return TestClient(app, base_url="https://testserver", headers=headers)


def _sign_up(app, name="alice") -> TestClient:
    client = _client(app)
    answer = client.post("/api/signup", json={
        "username": name, "password": GOOD, "agrees_public": True})
    assert answer.status_code == 201, answer.text
    return client


def _root(config) -> Path:
    return Path(config.store_root)


# ---- moderation ----


def test_the_operator_edits_and_clears_a_description(tmp_path) -> None:
    config, app = _world(tmp_path)
    alice = _sign_up(app)
    alice.put("/api/account", json={"description": "first words"})
    operator = _client(app, OPERATOR)
    edited = operator.put("/api/dev/players/alice/description",
                          json={"description": "kinder words"})
    assert edited.status_code == 200
    assert alice.get("/api/me").json()["description"] == "kinder words"
    operator.put("/api/dev/players/alice/description",
                 json={"description": ""})
    assert alice.get("/api/me").json()["description"] == ""
    # No revoke: the session and the status stay.
    assert store.read_player_record(_root(config), "alice").status == "active"
    too_long = operator.put("/api/dev/players/alice/description",
                            json={"description": "x" * 501})
    assert too_long.status_code == 400


def test_the_operator_replaces_and_removes_an_avatar(tmp_path) -> None:
    config, app = _world(tmp_path)
    alice = _sign_up(app)
    operator = _client(app, OPERATOR)
    put = operator.put("/api/dev/players/alice/avatar", content=PNG)
    assert put.status_code == 200 and put.json()["avatar_hash"]
    assert alice.get("/api/me").json()["avatar_hash"] \
        == put.json()["avatar_hash"]
    bad = operator.put("/api/dev/players/alice/avatar", content=b"not art")
    assert bad.status_code == 400
    removed = operator.delete("/api/dev/players/alice/avatar")
    assert removed.json()["avatar_hash"] is None
    assert alice.get("/api/me").json()["avatar_hash"] is None
    assert store.read_player_record(_root(config), "alice").status == "active"


def test_moderation_wants_the_operator(tmp_path) -> None:
    _config, app = _world(tmp_path)
    _sign_up(app)
    stranger = _client(app)
    assert stranger.put("/api/dev/players/alice/description",
                        json={"description": "x"}).status_code == 404


def _config_file(tmp_path, config) -> Path:
    path = tmp_path / "service.json"
    path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port}))
    return path


def test_the_moderation_commands(tmp_path, capsys) -> None:
    config, app = _world(tmp_path)
    alice = _sign_up(app)
    path = _config_file(tmp_path, config)
    art = tmp_path / "art.png"
    art.write_bytes(PNG)

    def run(*words: str) -> int:
        return players.main(["--service-config", str(path), *words])

    assert run("set-description", "--player", "alice", "--text", "hi") == 0
    assert alice.get("/api/me").json()["description"] == "hi"
    assert run("clear-description", "--player", "alice") == 0
    assert alice.get("/api/me").json()["description"] == ""
    assert run("set-avatar", "--player", "alice", "--file", str(art)) == 0
    assert alice.get("/api/me").json()["avatar_hash"]
    assert run("clear-avatar", "--player", "alice") == 0
    assert alice.get("/api/me").json()["avatar_hash"] is None
    art.write_bytes(b"x" * (2 * 1024 * 1024))
    assert run("set-avatar", "--player", "alice", "--file", str(art)) == 1
    assert "refused:" in capsys.readouterr().err


def test_the_delete_command_takes_two_steps(tmp_path, capsys) -> None:
    config, app = _world(tmp_path)
    _sign_up(app)
    path = _config_file(tmp_path, config)

    def run(*words: str) -> int:
        return players.main(["--service-config", str(path), *words])

    assert run("delete", "--player", "alice") == 0
    printed = capsys.readouterr().out
    assert "nothing changed" in printed and "--confirm alice" in printed
    assert "snapshot" in printed
    assert store.read_player_or_none(_root(config), "alice") is not None
    assert run("delete", "--player", "alice", "--confirm", "alicia") == 1
    assert store.read_player_or_none(_root(config), "alice") is not None
    assert run("delete", "--player", "alice", "--confirm", "alice") == 0
    assert "deleted" in capsys.readouterr().out
    assert store.read_player_or_none(_root(config), "alice") is None


# ---- deletion ----


def _played(config, player: str, day: str = "2026-08-12") -> None:
    """A stored send and trial row for a player, by hand."""
    root = _root(config)
    store.write_once_json(store.submission_path(root, day, player),
                          {"day": day, "player": player, "record": {}})
    store.write_once_json(store.trial_row_path(root, day, player),
                          {"p": 0.5})


def test_the_preview_changes_nothing(tmp_path) -> None:
    config, app = _world(tmp_path)
    _sign_up(app)
    root = _root(config)
    before = sorted(str(path) for path in root.rglob("*"))
    preview = _client(app, OPERATOR).get(
        "/api/dev/players/alice/deletion").json()
    assert preview["player"] == "alice"
    assert preview["has_password"] is True
    assert sorted(str(path) for path in root.rglob("*")) == before


def test_a_confirmation_that_does_not_agree_deletes_nothing(tmp_path) -> None:
    config, app = _world(tmp_path)
    _sign_up(app)
    operator = _client(app, OPERATOR)
    for confirm in ("Alice", "bob", "", None):
        answer = operator.post("/api/dev/players/alice/delete",
                               json={"confirm": confirm})
        assert answer.status_code == 409
    assert store.read_player_or_none(_root(config), "alice") is not None


def _assert_deleted(config, deleted_by: str) -> str:
    root = _root(config)
    deletion = store.read_deletion_or_none(root, "alice")
    assert deletion is not None and deletion.deleted_by == deleted_by
    assert store.read_player_or_none(root, "alice") is None
    assert store.read_account_or_none(root, "alice") is None
    assert store.read_credential_or_none(root, "alice") is None
    assert not store.avatar_path(root, "alice").exists()
    assert store.list_sessions(root, "alice") == ()
    # The raw records, the consent, and the claim stay.
    assert store.submission_path(root, "2026-08-12", "alice").is_file()
    assert store.trial_row_path(root, "2026-08-12", "alice").is_file()
    assert store.read_consent_or_none(root, "alice", 1) is not None
    assert store.read_claim_or_none(root, "alice") is not None
    assert store.read_identifier_or_none(root, "alice") \
        == deletion.identifier
    return deletion.identifier


def test_the_operator_deletes_an_account(tmp_path) -> None:
    config, app = _world(tmp_path)
    alice = _sign_up(app)
    alice.put("/api/account/avatar", content=PNG)
    _played(config, "alice")
    answer = _client(app, OPERATOR).post("/api/dev/players/alice/delete",
                                         json={"confirm": "alice"})
    assert answer.status_code == 200 and answer.json()["deleted"] is True
    _assert_deleted(config, "operator")
    # Each device of before is signed out.
    assert alice.get("/api/me").status_code == 401


def test_a_deleted_name_cannot_sign_in_or_sign_up(tmp_path) -> None:
    config, app = _world(tmp_path)
    _sign_up(app)
    players.delete_player(config, player="alice", confirm="alice")
    client = _client(app)
    signin = client.post("/api/signin",
                         json={"username": "alice", "password": GOOD})
    assert signin.status_code == 401
    again = client.post("/api/signup", json={
        "username": "Alice", "password": GOOD, "agrees_public": True})
    assert again.status_code == 409
    with pytest.raises(store.StoreError, match="deleted account"):
        players.make_player(config, player="alice", clock=lambda: FIXED_CLOCK)
    with pytest.raises(store.StoreError, match="cannot be restored"):
        players.restore_player(config, player="alice",
                               instant=datetime.datetime.now(datetime.UTC))


def test_the_player_deletes_their_own_account(tmp_path) -> None:
    config, app = _world(tmp_path)
    alice = _sign_up(app)
    _played(config, "alice")
    wrong_name = alice.post("/api/account/delete",
                            json={"username": "bob", "password": GOOD})
    assert wrong_name.status_code == 400
    wrong_password = alice.post("/api/account/delete", json={
        "username": "alice", "password": "not the password"})
    assert wrong_password.status_code == 403
    assert wrong_password.json() == {"cause": "password"}
    assert store.read_player_or_none(_root(config), "alice") is not None
    done = alice.post("/api/account/delete",
                      json={"username": "alice", "password": GOOD})
    assert done.status_code == 200
    assert auth.SESSION_COOKIE in done.headers.get("set-cookie", "")
    _assert_deleted(config, "player")
    assert alice.get("/api/me").status_code == 401


def test_an_account_with_no_password_cannot_delete_itself(tmp_path) -> None:
    config, app = _world(tmp_path)
    _record, token = mint_player(config, player="ade", display_name="ade")
    client = _client(app)
    client.cookies.set(auth.SESSION_COOKIE,
                       plant_session(_root(config), token))
    answer = client.post("/api/account/delete",
                         json={"username": "ade", "password": "anything"})
    assert answer.status_code == 409
    assert answer.json()["cause"] == "no-password"
    assert store.read_player_or_none(_root(config), "ade") is not None


def test_the_player_deletion_wants_the_origin(tmp_path) -> None:
    config, app = _world(tmp_path)
    alice = _sign_up(app)
    cookie = alice.cookies.get(auth.SESSION_COOKIE)
    crossed = TestClient(app, base_url="https://testserver",
                         headers={"origin": "https://elsewhere.example"})
    crossed.cookies.set(auth.SESSION_COOKIE, cookie)
    answer = crossed.post("/api/account/delete",
                          json={"username": "alice", "password": GOOD})
    assert answer.status_code == 403
    assert store.read_player_or_none(_root(config), "alice") is not None


def test_a_deletion_that_stopped_finishes_on_a_second_call(tmp_path) -> None:
    config, app = _world(tmp_path)
    _sign_up(app)
    root = _root(config)
    # The deletion record and nothing else, as after a stop.
    identifier = store.ensure_identifier(root, "alice", FIXED_CLOCK)
    store.write_once_json(store.deletion_path(root, "alice"), {
        "player": "alice", "identifier": identifier,
        "deleted_at": FIXED_CLOCK, "deleted_by": "operator"})
    players.delete_player(config, player="alice", confirm="alice")
    assert store.read_player_or_none(root, "alice") is None
    assert store.read_credential_or_none(root, "alice") is None


# ---- the anonymous name on each surface ----


DAYS = ("2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04")


def _send(root: Path, day: str, player: str) -> None:
    store.write_once_json(
        store.submission_path(root, day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK,
         "record": {**mixed_wire_record(), "impressions": ["a lake"]}})


@pytest.fixture(scope="module")
def played(tmp_path_factory):
    """Four revealed days of a production pool with alice and bob, then
    alice's account deleted by the operator. Alice has three earlier
    days on the last board, thus the floor shows her row to bob."""
    base = tmp_path_factory.mktemp("md1-played")
    fixture = build_service_fixture(base, dev_only=False, with_credits=True)
    config = dataclasses.replace(fixture["service_config"], signup="open")
    app = create_app(config, dev_mode=True, operator_token=OPERATOR_TOKEN,
                     digester=QuickDigester(), usual_passwords=frozenset())
    alice, bob = _sign_up(app), _sign_up(app, "bob")
    alice.put("/api/account/avatar", content=PNG)
    root = _root(config)
    for day in DAYS:
        open_day(config, date=day, clock=lambda: FIXED_CLOCK,
                 pick_seed="a" * 32, secret="b" * 64)
        _send(root, day, "alice")
        _send(root, day, "bob")
        close_day(config, clock=lambda: FIXED_CLOCK)
        reveal_day(config, clock=lambda: FIXED_CLOCK)
    answer = _client(app, OPERATOR).post("/api/dev/players/alice/delete",
                                         json={"confirm": "alice"})
    assert answer.status_code == 200
    return {"config": config, "root": root, "bob": bob, "base": base,
            "identifier": answer.json()["identifier"]}


def test_the_daily_board_shows_the_identifier(played) -> None:
    rows = played["bob"].get(f"/api/leaderboard?day={DAYS[-1]}").json()["rows"]
    by_name = {row["player"]: row for row in rows}
    assert set(by_name) == {"bob", played["identifier"]}
    gone = by_name[played["identifier"]]
    assert gone["display_name"] == played["identifier"]
    assert gone["avatar_hash"] is None
    assert gone["p"] is not None
    assert "alice" not in json.dumps(rows)


def test_the_skill_board_shows_the_identifier(played) -> None:
    root, config = played["root"], played["config"]
    record = store.read_day_record(root, DAYS[-1])
    board = rollup.skill_board_path(Path(config.data_root),
                                    record.scoring_config_hash)
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(json.dumps({
        "active": True, "format": rollup.ROLLUP_FORMAT,
        "rows": [{"player": "alice"}, {"player": "bob"}]}))
    rows = played["bob"].get("/api/leaderboard/skill").json()["rows"]
    assert [row["player"] for row in rows] == [played["identifier"], "bob"]
    assert rows[0]["avatar_hash"] is None
    assert "alice" not in json.dumps(rows)


def test_the_public_build_shows_the_identifier(played) -> None:
    out = played["base"] / "public"
    public.build(played["root"], Path(played["config"].data_root), out,
                 snapshot_date="2026-12-05", built_at=FIXED_CLOCK,
                 version="test")
    with sqlite3.connect(out / "starvector-public-2026-12-05.sqlite") as db:
        rows = dict(db.execute("SELECT player, named FROM players"))
        assert rows == {"bob": 1, played["identifier"]: 0}
        assert db.execute("SELECT COUNT(*) FROM trials WHERE player = ?",
                          (played["identifier"],)).fetchone()[0] == len(DAYS)
