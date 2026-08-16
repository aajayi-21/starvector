"""Integration: invited players and the session (spec M1 section 4).

The token parse, the invite gate, the cookie attributes, and the one
constant refusal. Each refusal is asked two times and compared as
bytes: a body that differs by condition is an oracle that tells an
outsider who is stored.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture

from service import auth, store
from service.day import open_day
from service.server import create_app

DAY = "2026-08-12"
ALICE_SECRET = "1" * 43
BRU_SECRET = "2" * 43


def _mint(root: Path, player: str, display_name: str, secret: str) -> str:
    """Store one player record and answer the invite token."""
    token, digest = auth.mint_token(player, secret=secret)
    store.write_player_record(root, store.PlayerRecord(
        player=player, display_name=display_name, token_hash=digest,
        created_at=FIXED_CLOCK, status="active"))
    return token


def _world(tmp_path, *, players=(("ade", "Ade", ALICE_SECRET),)):
    fixture = build_service_fixture(tmp_path)
    tokens = {name: _mint(fixture["store"], name, label, secret)
              for name, label, secret in players}
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    # https, because http.cookiejar stores a cookie with the
    # transport flag sent from an http address and then does not
    # send it back. Testing the deployed attribute set beats
    # weakening it for the test.
    client = TestClient(create_app(fixture["service_config"]),
                        base_url="https://testserver")
    return fixture, client, tokens


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


def test_the_join_gate_agrees_and_sets_the_cookie(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    answer = client.get(f"/join/{tokens['ade']}", follow_redirects=False)
    assert answer.status_code == 302
    assert answer.headers["location"] == "/"
    assert client.cookies.get(auth.SESSION_COOKIE) == tokens["ade"]


def test_the_cookie_attributes_are_the_specified_ones(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    answer = client.get(f"/join/{tokens['ade']}", follow_redirects=False)
    header = answer.headers["set-cookie"]
    assert header.startswith(f"{auth.SESSION_COOKIE}={tokens['ade']}")
    for attribute in ("Path=/", "Secure", "HttpOnly", "SameSite=Lax",
                      f"Max-Age={auth.SESSION_MAX_AGE}"):
        assert attribute in header
    assert auth.SESSION_MAX_AGE == 180 * 24 * 60 * 60


def test_the_transport_flag_turns_off_for_the_offline_tests(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    token = _mint(fixture["store"], "ade", "Ade", ALICE_SECRET)
    client = TestClient(create_app(fixture["service_config"],
                                   cookie_secure=False))
    header = client.get(f"/join/{token}",
                        follow_redirects=False).headers["set-cookie"]
    assert "Secure" not in header
    assert "HttpOnly" in header


def test_the_join_refusal_is_one_constant_body(tmp_path) -> None:
    fixture, client, _tokens = _world(tmp_path)
    root = fixture["store"]
    _mint(root, "revoked-one", "Revoked One", BRU_SECRET)
    store.set_player_status(root, "revoked-one", expect_status="active",
                            new_status="revoked")
    # The last one arrives percent-encoded and reaches the handler
    # with a newline at its end. A client refuses the raw byte in a
    # URL, thus this is the shape the guard sees in practice.
    refused = (
        "not-a-token",
        f"ade.{'9' * 43}",
        f"unknown-name.{ALICE_SECRET}",
        f"revoked-one.{BRU_SECRET}",
        f"ade.{ALICE_SECRET}%0A",
    )
    bodies, statuses = set(), set()
    for token in refused:
        for _ in range(2):
            answer = client.get(f"/join/{token}", follow_redirects=False)
            bodies.add(answer.content)
            statuses.add(answer.status_code)
    assert bodies == {b'{"detail":"unauthorized"}'}
    assert statuses == {401}


def test_a_revoked_player_stops_at_the_next_read(tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    assert client.get(f"/join/{tokens['ade']}",
                      follow_redirects=False).status_code == 302
    store.set_player_status(fixture["store"], "ade",
                            expect_status="active", new_status="revoked")
    assert client.get(f"/join/{tokens['ade']}",
                      follow_redirects=False).status_code == 401


def test_a_replaced_token_stops_the_earlier_invite(tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    _new_token, digest = auth.mint_token("ade", secret=BRU_SECRET)
    store.replace_player_token(fixture["store"], "ade",
                               expect_status="active",
                               new_token_hash=digest)
    assert client.get(f"/join/{tokens['ade']}",
                      follow_redirects=False).status_code == 401
    assert client.get(f"/join/ade.{BRU_SECRET}",
                      follow_redirects=False).status_code == 302


def test_the_join_path_writes_nothing(tmp_path) -> None:
    """No session table is built, thus nothing accumulates."""
    fixture, client, tokens = _world(tmp_path)

    def snapshot() -> dict:
        return {str(path): path.read_bytes()
                for path in Path(fixture["store"]).rglob("*")
                if path.is_file()}

    before = snapshot()
    client.get(f"/join/{tokens['ade']}", follow_redirects=False)
    client.get("/join/not-a-token", follow_redirects=False)
    assert snapshot() == before


def test_the_constant_time_compare_holds_odd_input() -> None:
    # An Authorization header arrives from the network, and
    # compare_digest refuses a str with characters above ASCII.
    assert auth.constant_time_equal("secret", "secret") is True
    assert auth.constant_time_equal("secret ", "secret") is False
    assert auth.constant_time_equal("a-much-longer-value", "s") is False
    assert auth.constant_time_equal("naïve", "secret") is False
    assert auth.constant_time_equal(None, "secret") is False
    assert auth.constant_time_equal(7, "secret") is False


def test_the_secret_compare_agrees_with_the_stored_digest() -> None:
    token, digest = auth.mint_token("ade", secret=ALICE_SECRET)
    assert token == f"ade.{ALICE_SECRET}"
    assert auth.secret_matches(ALICE_SECRET, digest) is True
    assert auth.secret_matches(BRU_SECRET, digest) is False


def test_a_minted_secret_has_the_pinned_shape() -> None:
    token, digest = auth.mint_token("ade")
    parsed = auth.parse_token(token)
    assert parsed is not None
    name, secret = parsed
    assert name == "ade"
    assert len(secret) == 43
    assert auth.secret_matches(secret, digest) is True


@pytest.mark.parametrize("name", ["ade.x", "A Player", "../escape"])
def test_a_name_the_store_refuses_cannot_make_a_token(name: str) -> None:
    # The mint builds a token from the text it gets, and the store
    # is what refuses the name. The two together mean no stored key
    # can make an ambiguous token.
    with pytest.raises(store.StoreError):
        store.check_player_name(name, "player")
