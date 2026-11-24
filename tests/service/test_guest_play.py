"""Integration: guest play and the claim at sign-up (spec IM1 section 7).

A world with instant mode open, sign-up open, the fake beacon, and a
proof of work with a small cost. The clock is the wall clock: the proof library
reads it.
"""

import dataclasses
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (QUICK_PROOF, QUICK_PROOF_KEYS, QuickDigester,
                         build_service_fixture, make_vp1, mixed_wire_record)

from service import guests, instant_store, limits, notice
from service.config import ServiceConfigError
from service.server import create_app

OPERATOR_TOKEN = "test-operator-token"
GOOD = "correct horse battery"
ORIGIN = {"origin": "https://testserver"}


def _config(tmp_path: Path, *, mode: str = "open", dev_only: bool = True):
    fixture = make_vp1(build_service_fixture(tmp_path, dev_only=dev_only),
                       tmp_path)
    config = dataclasses.replace(
        fixture["service_config"], signup="open", instant=mode,
        instant_day_cap=None if mode == "off" else 400)
    return fixture, config


def _app(config, **changes):
    arguments = {"operator_token": OPERATOR_TOKEN,
                 "digester": QuickDigester(),
                 "usual_passwords": frozenset(),
                 "proof_keys": QUICK_PROOF_KEYS,
                 "proof_settings": QUICK_PROOF}
    arguments.update(changes)
    return create_app(config, **arguments)


def _world(tmp_path: Path, **named):
    fixture, config = _config(tmp_path, **named)
    return fixture, _app(config)


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver", headers=ORIGIN)


def _proof(client, path: str = "/api/guest/challenge") -> str:
    import altcha

    answer = client.get(path)
    assert answer.status_code == 200, answer.text
    challenge = altcha.Challenge.from_dict(answer.json())
    solution = altcha.solve_challenge(challenge)
    assert solution is not None
    return altcha.Payload(challenge, solution).to_base64()


def _guest(app) -> tuple[TestClient, str]:
    """A browser with a new guest, and the identifier of the guest."""
    client = _client(app)
    answer = client.post("/api/guest", json={
        "proof": _proof(client), "agrees_public": True})
    assert answer.status_code == 201, answer.text
    return client, answer.json()["owner"]


def _play(client, app) -> dict:
    trial = client.post("/api/instant/start").json()
    sent = client.post(
        f"/api/instant/{trial['date']}/{trial['trial_id']}/send",
        json=mixed_wire_record())
    assert sent.status_code == 200, sent.text
    assert app.state.instant.tick() == 1
    return trial


def _sign_up(client, name: str):
    return client.post("/api/signup", json={
        "username": name, "password": GOOD, "agrees_public": True,
        "proof": _proof(client, "/api/signup/challenge")})


def _snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.mark.parametrize("mode", ["off", "accounts"])
def test_the_guest_paths_follow_the_switch(tmp_path, mode: str) -> None:
    fixture, app = _world(tmp_path, mode=mode)
    client = _client(app)
    assert client.get("/api/guest/challenge").status_code == 404
    answer = client.post("/api/guest", json={"agrees_public": True})
    assert answer.status_code == 404
    assert answer.content == b'{"detail":"not found"}'
    assert not (fixture["store"] / "guests").exists()


def test_open_guest_play_needs_the_proof_key(tmp_path) -> None:
    _, config = _config(tmp_path)
    with pytest.raises(ServiceConfigError, match="ALTCHA"):
        _app(config, proof_keys=None)


def test_a_new_guest_gets_a_record_a_consent_and_a_cookie(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    client = _client(app)
    answer = client.post("/api/guest", json={
        "proof": _proof(client), "agrees_public": True})
    assert answer.status_code == 201
    guest = answer.json()["owner"]
    assert answer.json()["kind"] == "guest"
    assert guests.is_guest_id(guest) and len(guest) == 22
    cookie = answer.headers["set-cookie"]
    assert cookie.startswith(f"sv_guest={guest}.")
    for part in ("Path=/", "Secure", "HttpOnly", "SameSite=Lax",
                 f"Max-Age={180 * 24 * 60 * 60}"):
        assert part in cookie
    secret = cookie.split(";")[0].split(".", 1)[1]
    directory = fixture["store"] / "guests" / guest
    assert sorted(path.name for path in directory.iterdir()) == [
        "consents", "guest.json"]
    # The store keeps the digest of the secret and not the secret.
    assert secret not in (directory / "guest.json").read_text()
    assert guests.agreed(fixture["store"], guest, notice.NOTICE_VERSION)


def test_a_guest_needs_a_proof_and_the_agreement(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    client = _client(app)
    no_proof = client.post("/api/guest", json={"agrees_public": True})
    assert no_proof.status_code == 400
    assert no_proof.content == b'{"cause":"proof"}'
    proof = _proof(client)
    no_notice = client.post("/api/guest", json={"proof": proof})
    assert no_notice.status_code == 400
    assert no_notice.content == b'{"cause":"notice"}'
    assert not (fixture["store"] / "guests").exists()
    # The refusal gave the proof back: the same proof makes the guest.
    made = client.post("/api/guest", json={"proof": proof,
                                           "agrees_public": True})
    assert made.status_code == 201


def test_a_page_of_a_different_site_makes_no_guest(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    client = TestClient(app, base_url="https://testserver",
                        headers={"origin": "https://evil.example"})
    answer = client.post("/api/guest", json={"agrees_public": True})
    assert answer.status_code == 403
    assert not (fixture["store"] / "guests").exists()


def test_one_proof_makes_one_guest_or_one_account(tmp_path) -> None:
    _, app = _world(tmp_path)
    first = _client(app)
    proof = _proof(first)
    assert first.post("/api/guest", json={
        "proof": proof, "agrees_public": True}).status_code == 201
    second = _client(app)
    again = second.post("/api/guest", json={"proof": proof,
                                            "agrees_public": True})
    assert again.status_code == 400
    account = second.post("/api/signup", json={
        "username": "opal", "password": GOOD, "agrees_public": True,
        "proof": proof})
    assert account.status_code == 400
    assert account.content == b'{"cause":"proof"}'


def test_a_browser_with_a_guest_keeps_that_guest(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    client, guest = _guest(app)
    before = _snapshot(fixture["store"])
    again = client.post("/api/guest", json={})
    assert again.status_code == 200
    assert again.json() == {"kind": "guest", "owner": guest}
    assert "set-cookie" not in again.headers
    assert _snapshot(fixture["store"]) == before


def test_a_guest_plays_and_has_the_cap_of_ruling_5(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    client, guest = _guest(app)
    view = client.get("/api/instant").json()
    assert view["kind"] == "guest" and view["owner"] == guest
    assert view["day_cap"] == view["left_today"] == 5
    for _ in range(limits.INSTANT_GUEST_DAY_CAP):
        _play(client, app)
    view = client.get("/api/instant").json()
    assert view["left_today"] == 0 and view["record"]["settled"] == 5
    before = _snapshot(fixture["store"])
    sixth = client.post("/api/instant/start")
    assert sixth.status_code == 429
    assert sixth.json() == {"cause": "instant-limit"}
    assert _snapshot(fixture["store"]) == before
    # The send record names the guest as its owner.
    trial = view["trials"][0]
    send = instant_store.read_send_or_none(
        fixture["store"], trial["date"], trial["trial_id"])
    assert (send.owner_kind, send.owner) == ("guest", guest)


def test_a_guest_gets_the_constant_401_on_each_daily_path(tmp_path) -> None:
    _, app = _world(tmp_path)
    client, _ = _guest(app)
    paths = [("get", "/api/day"), ("get", "/api/me"),
             ("get", "/api/history"), ("get", "/api/leaderboard"),
             ("get", "/api/leaderboard/skill"), ("get", "/api/sends"),
             ("get", "/api/submission"), ("get", "/api/reveal"),
             ("post", "/api/submission"), ("post", "/api/day/start"),
             ("get", "/api/sessions"), ("get", "/api/practice")]
    for method, path in paths:
        answer = getattr(client, method)(path)
        assert answer.status_code == 401, path
        assert answer.content == b'{"detail":"unauthorized"}', path
    # The fixed pages and the head of the chain are open to each reader.
    assert client.get("/api/about").status_code == 200
    assert client.get("/api/instant/head").status_code == 200


def test_a_bad_secret_is_not_a_guest(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    _, guest = _guest(app)
    stranger = _client(app)
    for value in (f"{guest}.{'x' * 43}", f"guest-{'0' * 16}.{'x' * 43}",
                  f"ade.{'x' * 43}", "not a token"):
        stranger.cookies.set(guests.GUEST_COOKIE, value)
        before = _snapshot(fixture["store"])
        answer = stranger.get("/api/instant")
        assert answer.status_code == 401
        assert stranger.post("/api/instant/start").status_code == 401
        assert _snapshot(fixture["store"]) == before
        stranger.cookies.clear()


def test_a_trial_of_a_guest_is_for_that_guest_alone(tmp_path) -> None:
    _, app = _world(tmp_path)
    first, _ = _guest(app)
    second, _ = _guest(app)
    trial = _play(first, app)
    path = f"/api/instant/{trial['date']}/{trial['trial_id']}"
    assert first.get(path).json()["status"] == "settled"
    assert second.get(path).status_code == 404
    assert second.get("/api/instant").json()["record"]["sent"] == 0


def test_the_cap_of_new_guests_for_one_client(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    for _ in range(limits.GUEST_CLIENT_CAP):
        _guest(app)
    client = _client(app)
    before = _snapshot(fixture["store"])
    refused = client.post("/api/guest", json={
        "proof": _proof(client), "agrees_public": True})
    assert refused.status_code == 429
    assert _snapshot(fixture["store"]) == before


def test_a_sign_up_claims_the_guest_of_its_browser(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    client, guest = _guest(app)
    first = _play(client, app)
    second = _play(client, app)
    trials = _snapshot(fixture["store"] / "instant")
    made = _sign_up(client, "opal")
    assert made.status_code == 201, made.text
    # The answer sets the session cookie and removes the guest cookie.
    cookies = made.headers.get_list("set-cookie")
    assert any(cookie.startswith("sv_session=opal.") for cookie in cookies)
    assert any(cookie.startswith("sv_guest=;") and "Max-Age=0" in cookie
               for cookie in cookies)
    claim = guests.read_claim_or_none(fixture["store"], guest)
    assert claim is not None and claim.player == "opal"
    # No trial file changes: the reader gets the owner through the claim.
    assert _snapshot(fixture["store"] / "instant") == trials
    view = client.get("/api/instant").json()
    assert view["kind"] == "account" and view["owner"] == "opal"
    assert view["record"]["sent"] == view["record"]["settled"] == 2
    assert {row["trial_id"] for row in view["trials"]} == {
        first["trial_id"], second["trial_id"]}
    # The cap of the account counts the sends of the guest today.
    assert view["day_cap"] == 20 and view["left_today"] == 18
    path = f"/api/instant/{first['date']}/{first['trial_id']}"
    assert client.get(path).json()["status"] == "settled"


def test_the_token_of_a_claimed_guest_opens_nothing(tmp_path) -> None:
    _, app = _world(tmp_path)
    client, guest = _guest(app)
    value = client.cookies.get(guests.GUEST_COOKIE)
    _play(client, app)
    assert _sign_up(client, "opal").status_code == 201
    stranger = _client(app)
    stranger.cookies.set(guests.GUEST_COOKIE, value)
    assert stranger.get("/api/instant").status_code == 401
    assert stranger.post("/api/instant/start").status_code == 401
    # A sign-up of that browser claims nothing a second time.
    assert _sign_up(stranger, "ruby").status_code == 201
    assert stranger.get("/api/instant").json()["record"]["sent"] == 0


def test_the_claim_is_there_after_a_start_of_the_server(tmp_path) -> None:
    fixture, config = _config(tmp_path)
    app = _app(config)
    client, _ = _guest(app)
    _play(client, app)
    assert _sign_up(client, "opal").status_code == 201
    session = client.cookies.get("sv_session")
    again = _client(_app(config))
    again.cookies.set("sv_session", session)
    view = again.get("/api/instant").json()
    assert view["owner"] == "opal" and view["record"]["sent"] == 1


def test_a_sign_in_does_not_claim(tmp_path) -> None:
    """Decision D7: the sign-up alone claims a guest."""
    fixture, app = _world(tmp_path)
    owner = _client(app)
    assert _sign_up(owner, "opal").status_code == 201
    client, guest = _guest(app)
    _play(client, app)
    signed = client.post("/api/signin", json={"username": "opal",
                                              "password": GOOD})
    assert signed.status_code == 200, signed.text
    assert guests.read_claim_or_none(fixture["store"], guest) is None
    # The account is the caller while its session is there.
    view = client.get("/api/instant").json()
    assert view["owner"] == "opal" and view["record"]["sent"] == 0
    # After the sign-out the guest is the caller again.
    assert client.post("/api/session/signout").status_code == 200
    view = client.get("/api/instant").json()
    assert view["owner"] == guest and view["record"]["sent"] == 1


def test_a_guest_agrees_to_a_new_notice_version(tmp_path,
                                                monkeypatch) -> None:
    fixture, app = _world(tmp_path, dev_only=False)
    client, guest = _guest(app)
    assert client.get("/api/instant").json()["needs_agreement"] is False
    monkeypatch.setattr(notice, "NOTICE_VERSION", notice.NOTICE_VERSION + 1)
    assert client.get("/api/instant").json()["needs_agreement"] is True
    refused = client.post("/api/instant/start")
    assert refused.status_code == 409
    assert refused.content == b'{"cause":"notice"}'
    agreed = client.post("/api/guest", json={"agrees_public": True})
    assert agreed.status_code == 200
    assert guests.agreed(fixture["store"], guest, notice.NOTICE_VERSION)
    assert client.post("/api/instant/start").status_code == 200


def test_guest_is_a_reserved_name(tmp_path) -> None:
    _, app = _world(tmp_path)
    client = _client(app)
    answer = client.post("/api/signup", json={
        "username": "guest", "password": GOOD, "agrees_public": True,
        "proof": _proof(client, "/api/signup/challenge")})
    assert answer.status_code == 400
    assert answer.json() == {"cause": "name-reserved"}
