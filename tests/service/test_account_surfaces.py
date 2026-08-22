"""Integration: the account surfaces (spec A1 items A2 and A3).

The grown /api/me, the two account writers, and the avatar serving
path. The leakage rules ride the standing walks: the new paths are
in the 401 walk, the open-day two-world compare, and the length
walk. This file pins the shapes, the caller scoping, and the
constant avatar refusal.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture

from service import auth, store
from service.day import open_day
from service.server import create_app

DAY = "2026-08-12"
OPERATOR_TOKEN = "test-operator-token"
ALICE_SECRET = "1" * 43
BRU_SECRET = "2" * 43
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 24


def _mint(root: Path, player: str, label: str, secret: str) -> str:
    token, digest = auth.mint_token(player, secret=secret)
    store.write_player_record(root, store.PlayerRecord(
        player=player, display_name=label, token_hash=digest,
        created_at=FIXED_CLOCK, status="active"))
    return token


def _sign_in(client: TestClient, token: str | None) -> TestClient:
    client.cookies.clear()
    if token is not None:
        client.cookies.set(auth.SESSION_COOKIE, token)
    return client


def _world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    tokens = {name: _mint(fixture["store"], name, label, secret)
              for name, label, secret in (("ade", "Ade", ALICE_SECRET),
                                          ("bru", "Bru Lin", BRU_SECRET))}
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    client = TestClient(
        create_app(fixture["service_config"],
                   operator_token=OPERATOR_TOKEN),
        base_url="https://testserver")
    return fixture, client, tokens


def test_the_me_surface_holds_the_empty_account(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    body = _sign_in(client, tokens["ade"]).get("/api/me").json()
    assert body["description"] == ""
    assert body["avatar_hash"] is None


def test_the_description_writes_and_the_me_surface_carries_it(
        tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    ade = _sign_in(client, tokens["ade"])
    answer = ade.put("/api/account",
                     json={"description": "I sketch coastlines."})
    assert answer.status_code == 200
    assert answer.json() == {"description": "I sketch coastlines."}
    assert ade.get("/api/me").json()["description"] \
        == "I sketch coastlines."


def test_the_writers_write_for_the_resolved_caller_alone(
        tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    _sign_in(client, tokens["ade"]).put(
        "/api/account", json={"description": "ade's words"})
    bru = _sign_in(client, tokens["bru"]).get("/api/me").json()
    assert bru["description"] == ""
    stored = store.read_account_or_none(fixture["store"], "ade")
    assert stored.description == "ade's words"
    assert store.read_account_or_none(fixture["store"], "bru") is None


def test_the_description_refusals_carry_the_cause(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    ade = _sign_in(client, tokens["ade"])
    long = ade.put("/api/account",
                   json={"description": "a" * 501})
    assert long.status_code == 400
    assert long.json()["cause"] == "bad-description"
    shape = ade.put("/api/account", content=b"not json",
                    headers={"content-type": "application/json"})
    assert shape.status_code == 400
    assert shape.json()["cause"] == "bad-shape"


def test_the_avatar_writes_serves_and_removes(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    ade = _sign_in(client, tokens["ade"])
    put = ade.put("/api/account/avatar", content=PNG)
    assert put.status_code == 200
    digest = put.json()["avatar_hash"]
    assert ade.get("/api/me").json()["avatar_hash"] == digest

    served = ade.get("/api/avatar/ade")
    assert served.status_code == 200
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"

    # Each signed-in caller reads it - the boards hold it (D5).
    theirs = _sign_in(client, tokens["bru"]).get("/api/avatar/ade")
    assert theirs.status_code == 200
    assert theirs.content == PNG

    gone = _sign_in(client, tokens["ade"]).delete("/api/account/avatar")
    assert gone.status_code == 200
    assert gone.json() == {"avatar_hash": None}
    assert ade.get("/api/avatar/ade").status_code == 404
    assert ade.get("/api/me").json()["avatar_hash"] is None


def test_the_avatar_refusals_carry_the_cause(tmp_path) -> None:
    _fixture, client, tokens = _world(tmp_path)
    ade = _sign_in(client, tokens["ade"])
    junk = ade.put("/api/account/avatar", content=b"not an image")
    assert junk.status_code == 400
    assert junk.json()["cause"] == "bad-avatar"
    oversized = ade.put("/api/account/avatar",
                        content=b"j" * (store.AVATAR_BYTE_CAP + 1))
    assert oversized.status_code == 400
    # The cap fires before the magic bytes (spec A1 section 9).
    assert "at most" in oversized.json()["detail"]


def test_one_constant_avatar_refusal_covers_each_condition(
        tmp_path) -> None:
    """No roster oracle: a name with no record and a player with no
    picture answer equal bytes, asked two times each."""
    _fixture, client, tokens = _world(tmp_path)
    ade = _sign_in(client, tokens["ade"])
    bodies, statuses = set(), set()
    for name in ("bru", "nobody-here", "ade"):
        for _ in range(2):
            answer = ade.get(f"/api/avatar/{name}")
            bodies.add(answer.content)
            statuses.add(answer.status_code)
    assert bodies == {b'{"detail":"no avatar"}'}
    assert statuses == {404}


def test_the_account_writers_want_the_cookie(tmp_path) -> None:
    _fixture, client, _tokens = _world(tmp_path)
    _sign_in(client, None)
    bodies, statuses = set(), set()
    for call in (
        lambda: client.put("/api/account", json={"description": "x"}),
        lambda: client.put("/api/account/avatar", content=PNG),
        lambda: client.delete("/api/account/avatar"),
    ):
        for _ in range(2):
            answer = call()
            bodies.add(answer.content)
            statuses.add(answer.status_code)
    assert bodies == {b'{"detail":"unauthorized"}'}
    assert statuses == {401}


def test_the_account_read_paths_keep_the_store_byte_equal(
        tmp_path) -> None:
    fixture, client, tokens = _world(tmp_path)
    ade = _sign_in(client, tokens["ade"])
    ade.put("/api/account", json={"description": "words"})
    ade.put("/api/account/avatar", content=PNG)

    def snapshot() -> dict:
        return {str(path): path.read_bytes()
                for path in Path(fixture["store"]).rglob("*")
                if path.is_file()}

    before = snapshot()
    ade.get("/api/me")
    ade.get("/api/avatar/ade")
    ade.get("/api/avatar/nobody-here")
    assert snapshot() == before


def test_the_fallback_world_edits_the_configured_players_account(
        tmp_path) -> None:
    """Ruling 7 of spec M1: with no record stored the identity is
    the configured player, and the account surfaces follow it."""
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    client = TestClient(create_app(fixture["service_config"]))
    answer = client.put("/api/account", json={"description": "solo"})
    assert answer.status_code == 200
    assert client.get("/api/me").json()["description"] == "solo"
    stored = store.read_account_or_none(fixture["store"], "ade")
    assert stored.description == "solo"
