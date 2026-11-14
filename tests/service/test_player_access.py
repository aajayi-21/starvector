"""Integration: stored players and the session (spec M1 section 4).

The token parse, the cookie attributes, and the one constant refusal.
Each refusal is asked two times and compared as bytes: a body that
differs by condition is an oracle that tells an outsider who is
stored. The players here have the record of before spec A2, with the
digest of an invite. That invite opens nothing from that spec on.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, QuickDigester, build_service_fixture,
                         plant_session, pinned_session_value)

from service import auth, signin, store
from service.day import open_day
from service.server import create_app

DAY = "2026-08-12"
ALICE_SECRET = "1" * 43
BRU_SECRET = "2" * 43
# create_app refuses to start with records stored and no token
# (spec M1 section 4), thus each world here carries one.
OPERATOR_TOKEN = "test-operator-token"
PASSWORD = "correct horse battery"


def _mint(root: Path, player: str, display_name: str, secret: str) -> str:
    """Store one player record of before spec A2, and answer the
    invite token that its digest names."""
    store.write_player_record(root, store.PlayerRecord(
        player=player, display_name=display_name,
        token_hash=auth.token_hash(secret),
        created_at=FIXED_CLOCK, status="active"))
    return f"{player}.{secret}"


def _sign_in(client: TestClient, token: str | None) -> TestClient:
    """Put the player's pinned session on the client, in the manner a
    browser holds one after the invite gate answers. None clears it."""
    client.cookies.clear()
    if token is not None:
        client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(token))
    return client


def _raw_cookie(client: TestClient, value: str) -> TestClient:
    """Put an arbitrary value in the cookie - the refusal tests."""
    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, value)
    return client


def _world(tmp_path, *, players=(("ade", "Ade", ALICE_SECRET),)):
    fixture = build_service_fixture(tmp_path)
    tokens = {name: _mint(fixture["store"], name, label, secret)
              for name, label, secret in players}
    for token in tokens.values():
        plant_session(fixture["store"], token)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    # https, because http.cookiejar stores a cookie with the
    # transport flag sent from an http address and then does not
    # send it back. Testing the deployed attribute set beats
    # weakening it for the test.
    client = TestClient(
        create_app(fixture["service_config"],
                   operator_token=OPERATOR_TOKEN, digester=QuickDigester(),
                   usual_passwords=frozenset()),
        base_url="https://testserver")
    return fixture, client, tokens


def _password_sign_in(client: TestClient, root: Path, name: str):
    """Give the player a password, and sign the client in with it."""
    import datetime

    signin.set_password(
        root, player=name, current_password=None, password=PASSWORD,
        digester=QuickDigester(), usual=frozenset(),
        instant=datetime.datetime.now(datetime.UTC))
    client.cookies.clear()
    return client.post("/api/signin",
                       json={"username": name, "password": PASSWORD},
                       headers={"origin": "https://testserver"})


def test_the_token_parse_is_unambiguous() -> None:
    good = auth.parse_token(f"ade.{ALICE_SECRET}")
    assert good == ("ade", ALICE_SECRET)
    for bad in (f"a.b.{ALICE_SECRET}", "ade.", f"ade.{'1' * 42}",
                f"ade.{'1' * 44}", f"ade.{'+' * 43}",
                f"ade.{ALICE_SECRET}\n", f"ADE.{ALICE_SECRET}",
                ALICE_SECRET, "", None, 7):
        assert auth.parse_token(bad) is None


def test_the_mint_stores_a_digest_and_not_the_secret(tmp_path) -> None:
    fixture, _client, _tokens = _world(tmp_path)
    for path in Path(fixture["store"]).rglob("*"):
        if path.is_file():
            assert ALICE_SECRET not in path.read_text(encoding="utf-8",
                                                      errors="replace")


def test_a_sign_in_sets_a_session_cookie_and_not_a_credential(
        tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    answer = _password_sign_in(client, fixture["store"], "ade")
    assert answer.status_code == 200
    value = client.cookies.get(auth.SESSION_COOKIE)
    assert value is not None and value != tokens["ade"]
    assert ALICE_SECRET not in value and PASSWORD not in value
    parsed = auth.parse_token(value)
    assert parsed is not None and parsed[0] == "ade"
    digest = auth.token_hash(parsed[1])
    assert store.read_session_or_none(fixture["store"], "ade",
                                      digest) is not None
    assert client.get("/api/me").json()["player"] == "ade"


def test_the_invite_in_a_cookie_signs_nobody_in(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    answer = _raw_cookie(client, tokens["ade"]).get("/api/me")
    assert answer.status_code == 401


def test_the_cookie_attributes_are_the_specified_ones(tmp_path) -> None:
    fixture, client, _tokens = _world(tmp_path)
    answer = _password_sign_in(client, fixture["store"], "ade")
    header = answer.headers["set-cookie"]
    assert header.startswith(f"{auth.SESSION_COOKIE}=ade.")
    assert ALICE_SECRET not in header
    for attribute in ("Path=/", "Secure", "HttpOnly", "SameSite=Lax",
                      f"Max-Age={auth.SESSION_MAX_AGE}"):
        assert attribute in header
    assert auth.SESSION_MAX_AGE == 180 * 24 * 60 * 60


def test_the_transport_flag_turns_off_for_the_offline_tests(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    _mint(fixture["store"], "ade", "Ade", ALICE_SECRET)
    client = TestClient(create_app(fixture["service_config"],
                                   cookie_secure=False,
                                   operator_token=OPERATOR_TOKEN,
                                   digester=QuickDigester(),
                                   usual_passwords=frozenset()),
                        base_url="http://testserver")
    signin.set_password(
        fixture["store"], player="ade", current_password=None,
        password=PASSWORD, digester=QuickDigester(), usual=frozenset(),
        instant=__import__("datetime").datetime.now(
            __import__("datetime").UTC))
    header = client.post(
        "/api/signin", json={"username": "ade", "password": PASSWORD},
        headers={"origin": "http://testserver"}).headers["set-cookie"]
    assert "Secure" not in header
    assert "HttpOnly" in header


def test_each_invite_address_gets_the_constant_404(tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    root = fixture["store"]
    _mint(root, "revoked-one", "Revoked One", BRU_SECRET)
    store.set_player_status(root, "revoked-one", expect_status="active",
                            new_status="revoked")

    def snapshot() -> dict:
        return {str(path): path.read_bytes()
                for path in Path(root).rglob("*") if path.is_file()}

    before = snapshot()
    client.cookies.clear()
    # The first one is the invite that the stored digest names. The
    # invite is gone (spec A2 ruling 2), thus it opens nothing too.
    asked = (
        tokens["ade"],
        "not-a-token",
        f"ade.{'9' * 43}",
        f"unknown-name.{ALICE_SECRET}",
        f"revoked-one.{BRU_SECRET}",
        f"ade.{ALICE_SECRET}%0A",
    )
    bodies, statuses = set(), set()
    for token in asked:
        for _ in range(2):
            answer = client.get(f"/join/{token}", follow_redirects=False)
            bodies.add(answer.content)
            statuses.add(answer.status_code)
            assert "set-cookie" not in answer.headers
    assert bodies == {b'{"detail":"not found"}'}
    assert statuses == {404}
    # No session and no other file comes from an invite address.
    assert snapshot() == before


def test_a_revoked_player_stops_at_the_next_read(tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    assert _sign_in(client, tokens["ade"]).get("/api/me").status_code == 200
    store.set_player_status(fixture["store"], "ade",
                            expect_status="active", new_status="revoked")
    assert client.get("/api/me").status_code == 401


def test_the_constant_time_compare_holds_odd_input() -> None:
    # An Authorization header arrives from the network, and
    # compare_digest refuses a str with characters above ASCII.
    assert auth.constant_time_equal("secret", "secret") is True
    assert auth.constant_time_equal("secret ", "secret") is False
    assert auth.constant_time_equal("a-much-longer-value", "s") is False
    assert auth.constant_time_equal("naïve", "secret") is False
    assert auth.constant_time_equal(None, "secret") is False
    assert auth.constant_time_equal(7, "secret") is False


_PLAYER_SURFACES = ("/api/day", "/api/reveal", "/api/history",
                    "/api/submission", "/api/leaderboard", "/api/me",
                    "/api/practice", "/api/avatar/ade")


def test_an_unknown_cookie_meets_the_constant_401(tmp_path) -> None:
    _fixture, client, _tokens = _world(tmp_path)
    bodies, statuses = set(), set()
    for token in (None, "garbage", f"ade.{'9' * 43}", f"ade.{ALICE_SECRET}"):
        if token is None:
            client.cookies.clear()
        else:
            _raw_cookie(client, token)
        for path in _PLAYER_SURFACES:
            for _ in range(2):
                answer = client.get(path)
                bodies.add(answer.content)
                statuses.add(answer.status_code)
    assert bodies == {b'{"detail":"unauthorized"}'}
    assert statuses == {401}


def _two_player_world(tmp_path):
    return _world(tmp_path, players=(("ade", "Ade", ALICE_SECRET),
                                     ("bru", "Bru", BRU_SECRET)))


def test_two_players_see_their_own_submitted_flags(tmp_path) -> None:
    from svc_fixture import mixed_wire_record

    fixture, client, tokens = _two_player_world(tmp_path)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    alice = _sign_in(client, tokens["ade"]).get("/api/day").json()
    bru = _sign_in(client, tokens["bru"]).get("/api/day").json()
    assert alice["player"] == "ade" and alice["submitted"] is True
    assert bru["player"] == "bru" and bru["submitted"] is False
    # The day itself is one shared trial (spec M1 ruling 2).
    assert alice["trial_code"] == bru["trial_code"]
    assert alice["commitment"] == bru["commitment"]


def test_the_stored_submission_is_the_callers_own(tmp_path) -> None:
    from svc_fixture import mixed_wire_record

    fixture, client, tokens = _two_player_world(tmp_path)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    mine = _sign_in(client, tokens["ade"]).get(f"/api/submission?day={DAY}")
    assert mine.status_code == 200
    assert mine.json()["trial_id"] == "f" * 32
    theirs = _sign_in(client,
                      tokens["bru"]).get(f"/api/submission?day={DAY}")
    assert theirs.status_code == 404
    assert theirs.content == b'{"detail":"no submission"}'


def test_two_players_see_their_own_me_and_streaks(tmp_path) -> None:
    _fixture, client, tokens = _two_player_world(tmp_path)
    for name in ("ade", "bru"):
        answer = _sign_in(client, tokens[name]).get("/api/me")
        assert answer.status_code == 200
        assert answer.json()["player"] == name


def test_the_me_surface_follows_the_cookie_and_not_the_config(
        tmp_path) -> None:
    # The configured player is 'ade'. With records stored, a cookie
    # for 'bru' must answer bru - the config must not leak through.
    _fixture, client, tokens = _two_player_world(tmp_path)
    answer = _sign_in(client, tokens["bru"]).get("/api/me")
    assert answer.json()["player"] == "bru"


def test_the_fallback_answers_as_today(tmp_path) -> None:
    """Ruling 7: with no record stored, nothing holds credentials."""
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    client = TestClient(create_app(fixture["service_config"]))
    assert store.any_player(fixture["store"]) is False
    for path in _PLAYER_SURFACES:
        assert client.get(path).status_code != 401
    assert client.get("/api/me").json()["player"] == "ade"
    assert client.get("/api/day").json()["player"] == "ade"


@pytest.mark.parametrize("name", ["ade.x", "A Player", "../escape"])
def test_a_name_the_store_refuses_cannot_make_a_token(name: str) -> None:
    # The mint builds a token from the text it gets, and the store
    # is what refuses the name. The two together mean no stored key
    # can make an ambiguous token.
    with pytest.raises(store.StoreError):
        store.check_player_name(name, "player")
