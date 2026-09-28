"""Integration: sessions, device codes, and sign-out (spec BR1 section 4).

A session is one signed-in device and the cookie holds it, not the
invite. A device code signs one more device in, one time, for ten
minutes. Sign-out ends one session, and a revoke ends each of them.
"""

import datetime
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, build_service_fixture,
                         pinned_session_value, plant_session)

from service import access, auth, limits, players, store
from service.day import open_day
from service.server import create_app, open_world_refusal, start_refusal

DAY = "2026-08-12"
OPERATOR_TOKEN = "test-operator-token"
ADE = f"ade.{'1' * 43}"
BRU = f"bru.{'2' * 43}"
IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
          "Mobile/15E148 Safari/604.1")
MAC_CHROME = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 "
              "Safari/537.36")


def _world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    for token, label in ((ADE, "Ade"), (BRU, "Bru")):
        name, secret = auth.parse_token(token)
        players.mint_player(config, player=name, display_name=label,
                            clock=lambda: FIXED_CLOCK, secret=secret)
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    app = create_app(config, operator_token=OPERATOR_TOKEN)
    return fixture, app


def _client(app, cookie: str | None = None,
            user_agent: str = MAC_CHROME) -> TestClient:
    client = TestClient(app, base_url="https://testserver",
                        headers={"user-agent": user_agent})
    if cookie is not None:
        client.cookies.set(auth.SESSION_COOKIE, cookie)
    return client


def _joined(app, token: str, user_agent: str = MAC_CHROME) -> TestClient:
    client = _client(app, user_agent=user_agent)
    assert client.get(f"/join/{token}",
                      follow_redirects=False).status_code == 302
    return client


# -- the pure helpers ---------------------------------------------------


@pytest.mark.parametrize(("typed", "stored"), [
    ("ABCD-EFGH", "ABCDEFGH"), ("abcd efgh", "ABCDEFGH"),
    (" abcdefgh ", "ABCDEFGH"), ("2345-6789", "23456789"),
])
def test_a_typed_code_normalizes(typed, stored) -> None:
    assert auth.normalize_device_code(typed) == stored


@pytest.mark.parametrize("bad", ["ABCD-EFG", "ABCD-EFGHJ", "ABCD-EFG0",
                                 "ABCD-EFGO", "ABCD-EFG1", "ABCD-EFGI",
                                 "ABCD-EFGL", "", None, 7, "A" * 40])
def test_other_text_is_not_a_code(bad) -> None:
    assert auth.normalize_device_code(bad) is None


def test_a_made_code_is_in_the_alphabet() -> None:
    for _ in range(50):
        code = auth.make_device_code()
        assert auth.normalize_device_code(code) == code
        assert auth.display_device_code(code) == f"{code[:4]}-{code[4:]}"


@pytest.mark.parametrize(("agent", "label"), [
    (IPHONE, "Safari on iPhone"),
    (MAC_CHROME, "Chrome on Mac"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
     "(KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0",
     "Edge on Windows"),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 "
     "Firefox/140.0", "Firefox on Linux"),
    ("Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like "
     "Gecko) Chrome/140.0 Mobile Safari/537.36", "Chrome on Android"),
    ("", "Unknown device"), (None, "Unknown device"),
    ("Playwright", "Unknown device"),
    ("Mozilla/5.0 Chrome/140.0", "Chrome"),
    ("SomeBot/1.0 (iPhone)", "Browser on iPhone"),
])
def test_the_device_label_names_browser_and_system(agent, label) -> None:
    assert auth.device_label(agent) == label


def test_the_clear_header_removes_the_one_cookie() -> None:
    header = auth.clear_cookie_header()
    assert header.startswith(f"{auth.SESSION_COOKIE}=;")
    for attribute in ("Path=/", "Secure", "HttpOnly", "SameSite=Lax",
                      "Max-Age=0"):
        assert attribute in header
    assert "Secure" not in auth.clear_cookie_header(secure=False)


# -- sessions -----------------------------------------------------------


def test_each_join_is_its_own_device(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    laptop = _joined(app, ADE)
    phone = _joined(app, ADE, user_agent=IPHONE)
    sessions = laptop.get("/api/sessions").json()["sessions"]
    assert [row["label"] for row in sessions] \
        == ["Chrome on Mac", "Safari on iPhone"]
    assert [row["current"] for row in sessions] == [True, False]
    assert phone.get("/api/me").json()["player"] == "ade"
    # The rows name no secret and no cookie value.
    text = json.dumps(sessions)
    assert laptop.cookies.get(auth.SESSION_COOKIE) not in text
    assert len(store.list_sessions(fixture["store"], "ade")) == 2


def test_sign_out_ends_this_device_alone(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    laptop = _joined(app, ADE)
    phone = _joined(app, ADE, user_agent=IPHONE)
    answer = laptop.post("/api/session/signout")
    assert answer.status_code == 200
    assert "Max-Age=0" in answer.headers["set-cookie"]
    assert laptop.get("/api/me").status_code == 401
    assert phone.get("/api/me").status_code == 200


def test_sign_out_with_no_session_still_answers(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    answers = [_client(app).post("/api/session/signout"),
               _client(app, "garbage").post("/api/session/signout")]
    assert {answer.status_code for answer in answers} == {200}


def test_a_device_signs_out_from_the_list(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    laptop = _joined(app, ADE)
    phone = _joined(app, ADE, user_agent=IPHONE)
    rows = laptop.get("/api/sessions").json()["sessions"]
    other = next(row for row in rows if not row["current"])
    assert laptop.delete(f"/api/sessions/{other['id']}").json() \
        == {"removed": 1}
    assert phone.get("/api/me").status_code == 401
    assert laptop.get("/api/me").status_code == 200


def test_a_session_id_that_is_not_yours_is_the_constant_404(
        tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    ade = _joined(app, ADE)
    bru = _joined(app, BRU)
    bru_id = bru.get("/api/sessions").json()["sessions"][0]["id"]
    bodies = {ade.delete(f"/api/sessions/{bru_id}").content,
              ade.delete(f"/api/sessions/{'f' * 64}").content,
              ade.delete("/api/sessions/not-a-digest").content}
    assert bodies == {b'{"detail":"no session"}'}
    assert bru.get("/api/me").status_code == 200


def test_sign_out_of_the_other_devices_keeps_this_one(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    laptop = _joined(app, ADE)
    phone = _joined(app, ADE, user_agent=IPHONE)
    tablet = _joined(app, ADE, user_agent="iPad Safari/1")
    assert laptop.post("/api/sessions/others/signout").json() \
        == {"removed": 2}
    assert laptop.get("/api/me").status_code == 200
    assert phone.get("/api/me").status_code == 401
    assert tablet.get("/api/me").status_code == 401


def test_a_session_past_its_life_stops(tmp_path, monkeypatch) -> None:
    from service import server

    _fixture, app = _world(tmp_path)
    laptop = _joined(app, ADE)
    assert laptop.get("/api/me").status_code == 200
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=auth.SESSION_MAX_AGE + 60)
    monkeypatch.setattr(server, "utc_now", lambda: later)
    assert laptop.get("/api/me").status_code == 401


def test_a_join_from_a_signed_in_browser_switches_players(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    browser = _joined(app, ADE)
    assert browser.get("/api/me").json()["player"] == "ade"
    assert browser.get(f"/join/{BRU}",
                       follow_redirects=False).status_code == 302
    assert browser.get("/api/me").json()["player"] == "bru"
    # The ade session stays - it is a device, and a second invite does
    # not sign it out from a different device.
    assert len(store.list_sessions(fixture["store"], "ade")) == 1


def test_revoke_ends_each_session_and_rotate_ends_none(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    config = fixture["service_config"]
    laptop = _joined(app, ADE)
    players.rotate_player(config, player="ade")
    # A new invite leaves the signed-in device signed in.
    assert laptop.get("/api/me").status_code == 200
    # The earlier invite stops.
    assert _client(app).get(f"/join/{ADE}",
                            follow_redirects=False).status_code == 401
    players.revoke_player(config, player="ade")
    assert laptop.get("/api/me").status_code == 401
    assert store.list_sessions(fixture["store"], "ade") == ()
    # Putting the player back gives a new invite and no device of
    # before.
    _record, token = players.restore_player(config, player="ade")
    assert laptop.get("/api/me").status_code == 401
    assert _joined(app, token).get("/api/me").status_code == 200


def test_the_operator_signout_and_session_list(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    config = fixture["service_config"]
    laptop = _joined(app, ADE)
    _joined(app, ADE, user_agent=IPHONE)
    now = datetime.datetime.now(datetime.UTC)
    lines = players.session_lines(config, player="ade", instant=now)
    assert len(lines) == 2
    assert any("Safari on iPhone" in line for line in lines)
    assert players.signout_player(config, player="ade") == 2
    assert laptop.get("/api/me").status_code == 401
    assert players.session_lines(config, player="ade", instant=now) \
        == ["no live sessions"]


# -- device codes -------------------------------------------------------


def test_a_device_code_signs_one_more_device_in(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    laptop = _joined(app, ADE)
    issued = laptop.post("/api/device-code").json()
    assert set(issued) == {"code", "expires_at"}
    assert len(issued["code"]) == 9 and issued["code"][4] == "-"
    phone = _client(app, user_agent=IPHONE)
    assert phone.get("/api/me").status_code == 401
    typed = issued["code"].lower().replace("-", " ")
    answer = phone.post("/api/device-code/redeem", json={"code": typed})
    assert answer.status_code == 200
    assert answer.json() == {"player": "ade", "display_name": "Ade"}
    assert phone.get("/api/me").json()["player"] == "ade"
    labels = [row["label"] for row in
              phone.get("/api/sessions").json()["sessions"]]
    assert "Safari on iPhone" in labels
    # One use: the second device with the same code is refused.
    again = _client(app).post("/api/device-code/redeem",
                              json={"code": issued["code"]})
    assert again.status_code == 400
    assert again.content == b'{"cause":"bad-code"}'


def test_each_bad_code_is_one_constant_body(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    root = fixture["store"]
    now = datetime.datetime.now(datetime.UTC)
    expired, _ = access.issue_device_code(
        root, "ade", now - datetime.timedelta(minutes=11), code="ABCDEFGH")
    revoked, _ = access.issue_device_code(root, "bru", now,
                                          code="HGFEDCBA")
    players.revoke_player(fixture["service_config"], player="bru")
    bodies = set()
    for body in ({"code": expired}, {"code": revoked},
                 {"code": "ZZZZ-ZZZZ"}, {"code": "not a code"}, {},
                 {"code": 7}, None):
        client = _client(app)
        answer = client.post("/api/device-code/redeem", json=body) \
            if body is not None \
            else client.post("/api/device-code/redeem", content=b"{oops")
        assert answer.status_code == 400
        bodies.add(answer.content)
        assert client.cookies.get(auth.SESSION_COOKIE) is None
    assert bodies == {b'{"cause":"bad-code"}'}
    # The expired code left the store at its first use.
    assert store.list_device_codes(root) == ()


def test_a_code_needs_a_session_and_an_account_world(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    assert _client(app).post("/api/device-code").status_code == 401
    alone = build_service_fixture(tmp_path / "alone")
    single = TestClient(create_app(alone["service_config"]))
    answer = single.post("/api/device-code")
    assert answer.status_code == 409
    assert answer.content == b'{"cause":"no-accounts"}'


def test_the_redemption_limiter_stops_a_guessing_client(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    laptop = _joined(app, ADE)
    code = laptop.post("/api/device-code").json()["code"]
    guesser = _client(app)
    for _ in range(limits.CLIENT_CAP):
        assert guesser.post("/api/device-code/redeem",
                            json={"code": "ZZZZ-ZZZZ"}).status_code == 400
    blocked = guesser.post("/api/device-code/redeem", json={"code": code})
    assert blocked.status_code == 429
    assert blocked.content == b'{"cause":"too-many-attempts"}'
    # The refused try did not use the code.
    other = _client(app, user_agent=IPHONE)
    # The TestClient peer is one address, thus a second client is the
    # same key - the edge names a different one.
    assert other.post("/api/device-code/redeem", json={"code": code},
                      headers={"x-forwarded-for": "203.0.113.9"}
                      ).status_code == 429


def test_the_limiter_window_and_the_global_cap() -> None:
    now = {"t": 0.0}
    limiter = limits.FailureLimiter(window_seconds=60, client_cap=2,
                                    global_cap=3, clock=lambda: now["t"])
    for _ in range(2):
        assert limiter.allowed("a")
        limiter.record_failure("a")
    assert not limiter.allowed("a")
    assert limiter.allowed("b")
    limiter.record_failure("b")
    # Three failures in the window: the global cap holds for each key.
    assert not limiter.allowed("c")
    now["t"] = 61.0
    assert limiter.allowed("a") and limiter.allowed("c")


def test_the_client_key_trusts_the_edge_entry_alone() -> None:
    assert limits.client_key("127.0.0.1", "10.0.0.1, 203.0.113.9") \
        == "203.0.113.9"
    assert limits.client_key("198.51.100.4", "203.0.113.9") \
        == "198.51.100.4"
    assert limits.client_key("127.0.0.1", None) == "127.0.0.1"
    assert limits.client_key(None, None) == "unknown"


def test_prune_removes_what_is_past_its_life(tmp_path) -> None:
    fixture, _app = _world(tmp_path)
    root = fixture["store"]
    old = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    access.open_session(root, "ade", user_agent=IPHONE, instant=old)
    access.issue_device_code(root, "ade", old, code="ABCDEFGH")
    live = plant_session(root, ADE)
    counts = access.prune(root, datetime.datetime.now(datetime.UTC))
    assert counts == {"sessions": 1, "device_codes": 1}
    remaining = store.list_sessions(root, "ade")
    assert len(remaining) == 1
    assert live == pinned_session_value(ADE)


# -- the door keeps each device ------------------------------------------


def test_a_revoked_player_gets_no_session_from_the_door(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.mint_player(config, player="ade", display_name="Ade",
                        clock=lambda: FIXED_CLOCK)
    players.revoke_player(config, player="ade")
    client = TestClient(create_app(config, dev_mode=True,
                                   cookie_secure=False,
                                   operator_token=OPERATOR_TOKEN))
    assert client.post("/api/door", json={"player": "ade"}).status_code \
        == 409
    assert store.list_sessions(fixture["store"], "ade") == ()


# -- the start-up guards ---------------------------------------------------


def test_the_flag_combinations() -> None:
    assert start_refusal(dev_mode=False, cookie_insecure=True,
                         single_player=False) is not None
    assert start_refusal(dev_mode=True, cookie_insecure=True,
                         single_player=False) is None
    assert start_refusal(dev_mode=True, cookie_insecure=False,
                         single_player=True) is not None
    assert start_refusal(dev_mode=False, cookie_insecure=False,
                         single_player=True) is None


def test_a_public_box_with_no_players_refuses() -> None:
    assert open_world_refusal(has_players=False, dev_mode=False,
                              single_player=False) is not None
    assert open_world_refusal(has_players=True, dev_mode=False,
                              single_player=False) is None
    assert open_world_refusal(has_players=False, dev_mode=True,
                              single_player=False) is None
    assert open_world_refusal(has_players=False, dev_mode=False,
                              single_player=True) is None


def test_the_entry_point_refuses_before_it_serves(tmp_path, capsys) -> None:
    from service import server

    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    path = Path(tmp_path) / "service.json"
    path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port}), encoding="utf-8")
    assert server.main(["--service-config", str(path)]) == 1
    assert "no player records" in capsys.readouterr().err
    assert server.main(["--service-config", str(path),
                        "--cookie-insecure"]) == 1
    assert "needs --dev" in capsys.readouterr().err
