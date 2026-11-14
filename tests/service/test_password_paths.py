"""The password paths of spec A2 section 8, through the server.

Sign-up, sign-in, recovery, the account moves, the limits, and the
start-up guards. The digester has no slow work.
"""

import dataclasses
import datetime

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, QuickDigester, build_service_fixture,
                         plant_session)

from service import auth, limits, players, signin, store
from service import server as server_module
from service.config import ServiceConfigError
from service.server import (create_app, open_world_refusal, pepper_refusal)

OPERATOR_TOKEN = "test-operator-token"
GOOD = "correct horse battery"
OTHER = "a second good password"
USUAL = frozenset({"passwordpassword"})
ORIGIN = {"origin": "https://testserver"}


def _world(tmp_path, signup: str = "open", digester=QuickDigester()):
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"], signup=signup)
    app = create_app(config, operator_token=OPERATOR_TOKEN,
                     digester=digester, usual_passwords=USUAL)
    return config, app


def _client(app, cookie: str | None = None) -> TestClient:
    client = TestClient(app, base_url="https://testserver", headers=ORIGIN)
    if cookie is not None:
        client.cookies.set(auth.SESSION_COOKIE, cookie)
    return client


def _sign_up(app, name="alice", password=GOOD) -> tuple[TestClient, dict]:
    client = _client(app)
    answer = client.post("/api/signup",
                         json={"username": name, "password": password})
    assert answer.status_code == 201, answer.text
    return client, answer.json()


def test_the_signup_probe_follows_the_switch(tmp_path) -> None:
    _config, app = _world(tmp_path)
    assert _client(app).get("/api/signup").json() == {"open": True}
    _config, closed = _world(tmp_path / "closed", signup="closed")
    probe = _client(closed).get("/api/signup")
    assert probe.status_code == 404
    made = _client(closed).post(
        "/api/signup", json={"username": "alice", "password": GOOD})
    assert made.status_code == 404
    assert made.content == probe.content


def test_sign_up_makes_the_account_and_signs_the_device_in(tmp_path) -> None:
    config, app = _world(tmp_path)
    client, body = _sign_up(app, name="Alice")
    assert body["player"] == "alice"
    assert body["display_name"] == "alice"
    code = auth.normalize_recovery_code(body["recovery_code"])
    assert code is not None and body["recovery_code"].count("-") == 5
    me = client.get("/api/me").json()
    assert me["player"] == "alice"
    assert me["has_password"] is True
    assert me["operator_code"] is None
    assert store.read_player_record(
        store_root(config), "alice").token_hash is None


def store_root(config):
    from pathlib import Path

    return Path(config.store_root)


def test_an_answer_with_a_recovery_code_is_not_stored_by_a_cache(
        tmp_path) -> None:
    _config, app = _world(tmp_path)
    client = _client(app)
    made = client.post("/api/signup",
                       json={"username": "alice", "password": GOOD})
    assert made.headers["cache-control"] == "no-store"
    assert "HttpOnly" in made.headers["set-cookie"]
    assert "Secure" in made.headers["set-cookie"]


@pytest.mark.parametrize("name, password, status, cause", [
    ("al", GOOD, 400, "name-rule"),
    ("admin", GOOD, 400, "name-reserved"),
    ("alice", "short", 400, "password-rule"),
    ("alice", "PasswordPassword", 400, "password-usual"),
])
def test_sign_up_names_the_rule_that_refuses(tmp_path, name, password,
                                             status, cause) -> None:
    _config, app = _world(tmp_path)
    answer = _client(app).post(
        "/api/signup", json={"username": name, "password": password})
    assert answer.status_code == status
    assert answer.json() == {"cause": cause}
    assert "set-cookie" not in answer.headers


def test_a_claimed_folded_shape_is_taken(tmp_path) -> None:
    _config, app = _world(tmp_path)
    _sign_up(app, name="no-one")
    answer = _client(app).post(
        "/api/signup", json={"username": "n0one", "password": GOOD})
    assert answer.status_code == 409
    assert answer.json() == {"cause": "name-taken"}


@pytest.mark.parametrize("path, body", [
    ("/api/signup", {"username": "alice", "password": GOOD}),
    ("/api/signin", {"username": "alice", "password": GOOD}),
    ("/api/recover", {"username": "alice", "recovery_code": "x",
                      "password": GOOD}),
])
def test_a_credential_post_wants_the_origin_and_the_media_type(
        tmp_path, path, body) -> None:
    _config, app = _world(tmp_path)
    bare = TestClient(app, base_url="https://testserver")
    assert bare.post(path, json=body).status_code == 403
    elsewhere = bare.post(path, json=body,
                          headers={"origin": "https://elsewhere.example"})
    assert elsewhere.status_code == 403
    assert elsewhere.json() == {"cause": "origin"}
    form = bare.post(path, data=body, headers=ORIGIN)
    assert form.status_code == 415
    assert not store.any_player(tmp_path / "store")


def test_sign_in_opens_a_session_for_the_pair(tmp_path) -> None:
    _config, app = _world(tmp_path)
    _sign_up(app)
    second = _client(app)
    answer = second.post("/api/signin",
                         json={"username": "ALICE", "password": GOOD})
    assert answer.status_code == 200
    assert answer.json() == {"player": "alice", "display_name": "alice"}
    assert second.get("/api/me").json()["player"] == "alice"
    devices = second.get("/api/sessions").json()["sessions"]
    assert len(devices) == 2


def test_each_pair_that_does_not_sign_in_gets_one_body(tmp_path) -> None:
    config, app = _world(tmp_path)
    _sign_up(app)
    _sign_up(app, name="revoked-one")
    players.revoke_player(config, player="revoked-one")
    bodies = set()
    for name, password in (("nobody", GOOD), ("alice", OTHER),
                           ("revoked-one", GOOD), ("not a name", GOOD),
                           ("alice", None)):
        answer = _client(app).post(
            "/api/signin", json={"username": name, "password": password})
        assert answer.status_code == 401
        assert "set-cookie" not in answer.headers
        bodies.add(answer.content)
    assert bodies == {b'{"cause":"sign-in"}'}


def test_recovery_replaces_the_password_and_ends_each_session(
        tmp_path) -> None:
    _config, app = _world(tmp_path)
    first, made = _sign_up(app)
    client = _client(app)
    answer = client.post("/api/recover", json={
        "username": "alice", "recovery_code": made["recovery_code"].lower(),
        "password": OTHER})
    assert answer.status_code == 200
    assert answer.headers["cache-control"] == "no-store"
    new_code = answer.json()["recovery_code"]
    assert new_code != made["recovery_code"]
    # The device of before is signed out, and this one is signed in.
    assert first.get("/api/me").status_code == 401
    assert client.get("/api/me").json()["player"] == "alice"
    assert _client(app).post(
        "/api/signin",
        json={"username": "alice", "password": GOOD}).status_code == 401
    assert _client(app).post(
        "/api/signin",
        json={"username": "alice", "password": OTHER}).status_code == 200


def test_each_recovery_that_does_not_work_gets_one_body(
        tmp_path, monkeypatch) -> None:
    config, app = _world(tmp_path)
    _first, made = _sign_up(app)
    _second, other = _sign_up(app, name="revoked-one")
    players.revoke_player(config, player="revoked-one")
    held, _usable = signin.issue_operator_code(
        store_root(config), player="alice",
        instant=datetime.datetime.now(datetime.UTC))
    used = made["recovery_code"]
    assert _client(app).post("/api/recover", json={
        "username": "alice", "recovery_code": used,
        "password": OTHER}).status_code == 200
    bodies = set()
    for name, code in (("nobody", used), ("alice", "ABCD" * 6),
                       ("alice", used), ("alice", held),
                       ("revoked-one", other["recovery_code"]),
                       ("alice", "not a code"), ("alice", None)):
        answer = _client(app).post("/api/recover", json={
            "username": name, "recovery_code": code, "password": GOOD})
        assert answer.status_code == 401, (name, code)
        bodies.add(answer.content)
    assert bodies == {b'{"cause":"recovery"}'}


def test_the_operator_code_works_after_its_hold(tmp_path,
                                                monkeypatch) -> None:
    config, app = _world(tmp_path)
    client, _made = _sign_up(app)
    now = datetime.datetime.now(datetime.UTC)
    code, usable_at = signin.issue_operator_code(
        store_root(config), player="alice", instant=now)
    view = client.get("/api/me").json()["operator_code"]
    assert view == {"issued_at": now.isoformat(), "usable_at": usable_at}
    attempt = {"username": "alice", "recovery_code": code, "password": OTHER}
    assert _client(app).post("/api/recover", json=attempt).status_code == 401
    monkeypatch.setattr(server_module, "utc_now",
                        lambda: now + datetime.timedelta(hours=24))
    assert _client(app).post("/api/recover", json=attempt).status_code == 200


def test_the_player_stops_the_operator_code_with_the_session(
        tmp_path, monkeypatch) -> None:
    config, app = _world(tmp_path)
    client, _made = _sign_up(app)
    now = datetime.datetime.now(datetime.UTC)
    code, _usable = signin.issue_operator_code(
        store_root(config), player="alice", instant=now)
    assert client.post("/api/account/recovery-code/stop").json() \
        == {"stopped": True}
    assert client.post("/api/account/recovery-code/stop").json() \
        == {"stopped": True}
    assert client.get("/api/me").json()["operator_code"] is None
    monkeypatch.setattr(server_module, "utc_now",
                        lambda: now + datetime.timedelta(days=2))
    assert _client(app).post("/api/recover", json={
        "username": "alice", "recovery_code": code,
        "password": OTHER}).status_code == 401
    assert _client(app).post(
        "/api/account/recovery-code/stop").status_code == 401


def test_a_password_change_ends_each_other_session(tmp_path) -> None:
    _config, app = _world(tmp_path)
    first, _made = _sign_up(app)
    second = _client(app)
    second.post("/api/signin", json={"username": "alice", "password": GOOD})
    wrong = first.post("/api/account/password", json={
        "current_password": "not the one", "password": OTHER})
    assert wrong.status_code == 403
    assert wrong.content == b'{"cause":"password"}'
    weak = first.post("/api/account/password", json={
        "current_password": GOOD, "password": "short"})
    assert weak.json() == {"cause": "password-rule"}
    changed = first.post("/api/account/password", json={
        "current_password": GOOD, "password": OTHER})
    assert changed.json() == {"changed": True, "signed_out": 1,
                              "recovery_code": None}
    assert first.get("/api/me").status_code == 200
    assert second.get("/api/me").status_code == 401


def test_a_new_recovery_code_wants_the_password(tmp_path) -> None:
    _config, app = _world(tmp_path)
    client, made = _sign_up(app)
    assert client.post("/api/account/recovery-code", json={
        "current_password": OTHER}).status_code == 403
    answer = client.post("/api/account/recovery-code",
                         json={"current_password": GOOD})
    assert answer.headers["cache-control"] == "no-store"
    new_code = answer.json()["recovery_code"]
    assert new_code != made["recovery_code"]
    assert _client(app).post("/api/recover", json={
        "username": "alice", "recovery_code": made["recovery_code"],
        "password": OTHER}).status_code == 401
    assert _client(app).post("/api/recover", json={
        "username": "alice", "recovery_code": new_code,
        "password": OTHER}).status_code == 200


def test_the_account_paths_want_a_session(tmp_path) -> None:
    _config, app = _world(tmp_path)
    for path in ("/api/account/password", "/api/account/recovery-code"):
        assert _client(app).post(
            path, json={"current_password": GOOD}).status_code == 401


def test_the_address_cap_stands_before_the_store(tmp_path,
                                                monkeypatch) -> None:
    _config, app = _world(tmp_path)
    _sign_up(app)
    client = _client(app)
    for number in range(limits.CLIENT_CAP):
        assert client.post("/api/signin", json={
            "username": f"name-{number}", "password": OTHER,
        }).status_code == 401

    def no_store_read(*_args, **_kwargs):
        raise AssertionError("the cap must answer before the store is read")

    monkeypatch.setattr(signin, "sign_in", no_store_read)
    monkeypatch.setattr(signin, "recover", no_store_read)
    capped = client.post("/api/signin",
                         json={"username": "alice", "password": GOOD})
    assert capped.status_code == 429
    assert capped.content == b'{"cause":"too-many-attempts"}'
    assert client.post("/api/recover", json={
        "username": "alice", "recovery_code": "x",
        "password": OTHER}).status_code == 429


def test_the_username_cap_counts_across_addresses(tmp_path) -> None:
    _config, app = _world(tmp_path)
    _sign_up(app)
    for number in range(limits.NAME_FAILURE_CAP):
        # Behind the edge the peer is loopback and the last forwarded
        # entry is the client: each try comes from a new address.
        client = TestClient(app, base_url="https://testserver",
                            headers=ORIGIN, client=("127.0.0.1", 50000))
        answer = client.post(
            "/api/signin", json={"username": "alice", "password": OTHER},
            headers={"x-forwarded-for": f"203.0.113.{number}"})
        assert answer.status_code == 401
    fresh = TestClient(app, base_url="https://testserver", headers=ORIGIN,
                       client=("127.0.0.1", 50000))
    good = fresh.post("/api/signin",
                      json={"username": "alice", "password": GOOD},
                      headers={"x-forwarded-for": "198.51.100.7"})
    assert good.status_code == 429
    # A different username from that address is not capped.
    other = fresh.post("/api/signin",
                       json={"username": "nobody", "password": GOOD},
                       headers={"x-forwarded-for": "198.51.100.7"})
    assert other.status_code == 401


def test_the_signup_cap_counts_the_accounts_made(tmp_path) -> None:
    _config, app = _world(tmp_path)
    client = _client(app)
    for number in range(limits.SIGNUP_CLIENT_CAP):
        # A refused sign-up is not an account made and does not count.
        assert client.post("/api/signup", json={
            "username": "al", "password": GOOD}).status_code == 400
        assert client.post("/api/signup", json={
            "username": f"player-{number}",
            "password": GOOD}).status_code == 201
    assert client.post("/api/signup", json={
        "username": "one-more", "password": GOOD}).status_code == 429
    assert limits.SIGNUP_CLIENT_CAP == 10
    assert limits.SIGNUP_GLOBAL_CAP == 1_000
    assert limits.SIGNUP_WINDOW_SECONDS == 24 * 60 * 60


def test_open_signup_has_no_fallback_identity(tmp_path) -> None:
    _config, app = _world(tmp_path)
    # No player record is stored, and no caller is the configured player.
    assert _client(app).get("/api/me").status_code == 401
    assert _client(app).get("/api/day").status_code == 401


def test_the_guards_of_an_open_signup(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"], signup="open")
    with pytest.raises(ServiceConfigError, match="operator token"):
        create_app(config, digester=QuickDigester(), usual_passwords=USUAL)
    with pytest.raises(ServiceConfigError, match="pepper"):
        create_app(config, operator_token=OPERATOR_TOKEN)
    store.write_player_record(store_root(config), store.PlayerRecord(
        player="ade", display_name="Ade", token_hash="a" * 64,
        created_at=FIXED_CLOCK, status="active"))
    with pytest.raises(ServiceConfigError, match="claim-names"):
        create_app(config, operator_token=OPERATOR_TOKEN,
                   digester=QuickDigester(), usual_passwords=USUAL)
    signin.claim_stored_names(store_root(config),
                              datetime.datetime.now(datetime.UTC))
    create_app(config, operator_token=OPERATOR_TOKEN,
               digester=QuickDigester(), usual_passwords=USUAL)


def test_the_start_refusals_of_spec_a2() -> None:
    assert open_world_refusal(has_players=False, dev_mode=False,
                              single_player=False, signup_open=True) is None
    assert "signup" in open_world_refusal(
        has_players=False, dev_mode=False, single_player=False)
    assert pepper_refusal(has_credentials=True, has_pepper=True) is None
    assert pepper_refusal(has_credentials=False, has_pepper=False) is None
    assert "pepper" in pepper_refusal(has_credentials=True, has_pepper=False)


def test_a_server_with_no_digester_has_no_password_paths(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    app = create_app(fixture["service_config"])
    client = _client(app)
    for path in ("/api/signin", "/api/recover", "/api/account/password",
                 "/api/account/recovery-code"):
        assert client.post(path, json={}).status_code == 404, path


def test_a_player_of_before_sets_a_first_password(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    root = store_root(config)
    store.ensure_store(root)
    store.write_player_record(root, store.PlayerRecord(
        player="bru", display_name="Bru", token_hash="a" * 64,
        created_at=FIXED_CLOCK, status="active"))
    app = create_app(config, operator_token=OPERATOR_TOKEN,
                     digester=QuickDigester(), usual_passwords=USUAL)
    client = _client(app, plant_session(root, f"bru.{'s' * 43}"))
    assert client.get("/api/me").json()["has_password"] is False
    answer = client.post("/api/account/password", json={"password": GOOD})
    assert answer.status_code == 200
    code = answer.json()["recovery_code"]
    assert auth.normalize_recovery_code(code) is not None
    assert client.get("/api/me").json()["has_password"] is True
    assert _client(app).post(
        "/api/signin",
        json={"username": "bru", "password": GOOD}).status_code == 200


def test_a_broken_credential_record_is_an_error_line_and_the_refusal(
        tmp_path, caplog) -> None:
    config, app = _world(tmp_path)
    _sign_up(app)
    store.credential_record_path(store_root(config), "alice").write_text("{")
    with caplog.at_level("ERROR", logger="starvector.credentials"):
        answer = _client(app).post(
            "/api/signin", json={"username": "alice", "password": GOOD})
    assert answer.status_code == 401
    assert answer.content == b'{"cause":"sign-in"}'
    assert "sign-in stopped on a stored record" in caplog.text
    assert GOOD not in caplog.text
