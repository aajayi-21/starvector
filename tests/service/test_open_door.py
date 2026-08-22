"""Integration: the open door (spec A1 item A4).

The development-only sign-in path. Off, the two paths
answer the dev surfaces' constant 404, thus production bytes do
not move. On, an unknown name mints, an active name turns its
token, and a revoked name is refused.
"""

import json

from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture

from service import auth, players, store
from service.day import open_day
from service.server import create_app

DAY = "2026-08-12"
OPERATOR_TOKEN = "test-operator-token"


def _world(tmp_path, *, dev_mode: bool, minted=()):
    fixture = build_service_fixture(tmp_path)
    for name, label, secret in minted:
        players.mint_player(fixture["service_config"], player=name,
                            display_name=label,
                            clock=lambda: FIXED_CLOCK, secret=secret)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    app = create_app(fixture["service_config"], dev_mode=dev_mode,
                     cookie_secure=False,
                     operator_token=OPERATOR_TOKEN if minted else None)
    return fixture, TestClient(app)


def test_the_door_off_answers_the_dev_surfaces_constant(
        tmp_path) -> None:
    _fixture, client = _world(tmp_path, dev_mode=False)
    constant = client.get("/api/dev/days")
    bodies, statuses = set(), set()
    for answer in (client.get("/api/door"),
                   client.get("/api/door"),
                   client.post("/api/door", json={"player": "walkin"}),
                   client.post("/api/door", json={"player": "walkin"})):
        bodies.add(answer.content)
        statuses.add(answer.status_code)
    assert bodies == {constant.content}
    assert statuses == {404}
    # The refused door minted nothing.
    assert store.any_player(_fixture["store"]) is False


def test_the_door_on_says_so(tmp_path) -> None:
    _fixture, client = _world(tmp_path, dev_mode=True)
    assert client.get("/api/door").json() == {"open": True}


def test_the_door_mints_and_signs_in(tmp_path) -> None:
    fixture, client = _world(tmp_path, dev_mode=True)
    answer = client.post("/api/door", json={"player": "walkin",
                                            "display_name": "Walk In"})
    assert answer.status_code == 200
    assert answer.json() == {"player": "walkin",
                             "display_name": "Walk In"}
    assert auth.SESSION_COOKIE in answer.headers["set-cookie"]
    me = client.get("/api/me").json()
    assert me["player"] == "walkin"
    assert me["display_name"] == "Walk In"
    record = store.read_player_record(fixture["store"], "walkin")
    assert record.status == "active"


def test_the_first_door_mint_flips_access_control_on(tmp_path) -> None:
    _fixture, client = _world(tmp_path, dev_mode=True)
    # Ruling 7: with no record stored, nothing holds credentials.
    assert client.get("/api/me").status_code == 200
    client.post("/api/door", json={"player": "walkin"})
    client.cookies.clear()
    assert client.get("/api/me").status_code == 401


def test_the_door_turns_an_active_players_token(tmp_path) -> None:
    fixture, client = _world(
        tmp_path, dev_mode=True,
        minted=(("ade", "Ade", "1" * 43),))
    earlier = f"ade.{'1' * 43}"
    client.cookies.set(auth.SESSION_COOKIE, earlier)
    assert client.get("/api/me").status_code == 200
    client.cookies.clear()
    answer = client.post("/api/door", json={"player": "ade"})
    assert answer.status_code == 200
    # The label stays the minted one - the door edits no record.
    assert answer.json()["display_name"] == "Ade"
    assert client.get("/api/me").json()["player"] == "ade"
    # Each other session of that player stops at its next read.
    client.cookies.clear()
    client.cookies.set(auth.SESSION_COOKIE, earlier)
    assert client.get("/api/me").status_code == 401


def test_the_door_cannot_put_a_revoked_player_back(tmp_path) -> None:
    fixture, client = _world(
        tmp_path, dev_mode=True,
        minted=(("ade", "Ade", "1" * 43),))
    players.revoke_player(fixture["service_config"], player="ade")
    answer = client.post("/api/door", json={"player": "ade"})
    assert answer.status_code == 409
    assert answer.json() == {"cause": "revoked"}
    assert store.read_player_record(fixture["store"],
                                    "ade").status == "revoked"


def test_the_door_refuses_an_illegal_name_or_label(tmp_path) -> None:
    _fixture, client = _world(tmp_path, dev_mode=True)
    bad_name = client.post("/api/door", json={"player": "A Player"})
    assert bad_name.status_code == 400
    assert bad_name.json()["cause"] == "bad-player"
    bad_label = client.post("/api/door",
                            json={"player": "walkin",
                                  "display_name": " padded "})
    assert bad_label.status_code == 400
    assert bad_label.json()["cause"] == "bad-display-name"
    assert store.any_player(_fixture["store"]) is False


def test_a_mint_race_answers_a_refusal_and_not_a_crash(
        tmp_path, monkeypatch) -> None:
    """The door's read and its write can straddle a mint from a
    different process - the CLI on the box. The store's one-write
    guard raises, and the door must answer a refusal. The
    monkeypatch stands in for the interleaving, which two
    processes cannot rehearse in one test."""
    _fixture, client = _world(tmp_path, dev_mode=True)

    def collide(*_args, **_kwargs):
        raise store.StoreError("the store is one-write and the file "
                               "exists")

    monkeypatch.setattr(players, "mint_player", collide)
    answer = client.post("/api/door", json={"player": "walkin"})
    assert answer.status_code == 409
    assert answer.json()["cause"] == "refused"


def test_the_door_mint_and_the_console_mint_write_one_shape(
        tmp_path) -> None:
    fixture, client = _world(tmp_path, dev_mode=True)
    client.post("/api/door", json={"player": "walkin"})
    players.mint_player(fixture["service_config"], player="cyd",
                        display_name="Cyd",
                        clock=lambda: FIXED_CLOCK, secret="3" * 43)
    raw = {}
    for name in ("walkin", "cyd"):
        path = store.player_record_path(fixture["store"], name)
        raw[name] = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw["walkin"]) == set(raw["cyd"])
    assert raw["walkin"]["status"] == raw["cyd"]["status"] == "active"
