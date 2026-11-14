"""The notice that results are public, the start record, and the
operator's records of the public database (spec R1 sections 3, 4, 8,
and 9).
"""

import dataclasses
import datetime
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, QuickDigester, build_service_fixture,
                         mixed_wire_record)

from service import auth, notice, players, signin, store
from service.config import ServiceConfigError, parse_service_config
from service.day import open_day
from service.server import create_app

TOKEN = "test-operator-token"
GOOD = "correct horse battery"
ORIGIN = {"origin": "https://testserver"}
NOW = datetime.datetime(2026, 11, 13, 12, 0, tzinfo=datetime.UTC)
DAY = "2026-08-12"


# -- the store records --------------------------------------------------


def test_a_consent_is_one_file_for_each_version(tmp_path) -> None:
    assert store.write_consent(tmp_path, "alice", 1, "t1") is True
    # A second agreement to one version keeps the first time.
    assert store.write_consent(tmp_path, "alice", 1, "t2") is False
    assert store.read_consent_or_none(tmp_path, "alice", 1)["agreed_at"] \
        == "t1"
    # A new version is a second file, and the earlier one stays.
    assert store.read_consent_or_none(tmp_path, "alice", 2) is None
    assert store.write_consent(tmp_path, "alice", 2, "t3") is True
    assert store.read_consent_or_none(tmp_path, "alice", 1)["agreed_at"] \
        == "t1"
    assert store.read_consent_or_none(tmp_path, "nobody", 1) is None
    for bad in (0, True, "1"):
        with pytest.raises(store.StoreError):
            store.write_consent(tmp_path, "alice", bad, "t")


def test_a_consent_record_that_does_not_parse_is_not_an_agreement(
        tmp_path) -> None:
    store.write_consent(tmp_path, "alice", 1, "t1")
    store.consent_path(tmp_path, "alice", 1).write_text(
        json.dumps({"player": "bru", "notice": 1, "agreed_at": "t"}))
    with pytest.raises(store.StoreError):
        store.read_consent_or_none(tmp_path, "alice", 1)


def test_the_first_start_stays(tmp_path) -> None:
    assert store.read_start_or_none(tmp_path, DAY, "alice") is None
    assert store.write_start(tmp_path, DAY, "alice", "t1") is True
    assert store.write_start(tmp_path, DAY, "alice", "t2") is False
    assert store.read_start_or_none(tmp_path, DAY, "alice") == "t1"
    with pytest.raises(store.StoreError):
        store.write_start(tmp_path, "not-a-day", "alice", "t")
    # A start is not a submission.
    assert store.list_submissions(tmp_path, DAY) == ()


def test_the_withhold_record_writes_lists_and_goes(tmp_path) -> None:
    record = store.WithheldRecord(day=DAY, player="alice",
                                  withheld_at="t1", note="a street address")
    store.write_withheld(tmp_path, record)
    assert store.read_withheld_or_none(tmp_path, DAY, "alice") == record
    assert store.list_withheld(tmp_path) == (record,)
    assert store.remove_withheld(tmp_path, DAY, "alice") is True
    assert store.remove_withheld(tmp_path, DAY, "alice") is False
    assert store.list_withheld(tmp_path) == ()
    for note in ("", "x" * 201, "line\nbreak"):
        with pytest.raises(store.StoreError):
            store.write_withheld(tmp_path,
                                 dataclasses.replace(record, note=note))


def test_an_identifier_is_random_and_made_one_time(tmp_path) -> None:
    assert store.read_identifier_or_none(tmp_path, "alice") is None
    first = store.ensure_identifier(tmp_path, "alice", "t1")
    assert first.startswith("anon-") and len(first) == 21
    assert "alice" not in first
    assert store.ensure_identifier(tmp_path, "alice", "t2") == first
    assert store.ensure_identifier(tmp_path, "bru", "t1") != first
    with pytest.raises(store.StoreError):
        store.ensure_identifier(tmp_path, "cyd", "t1", identifier="cyd")


def test_a_revoke_makes_the_identifier(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    players.make_player(config, player="ade", clock=lambda: FIXED_CLOCK)
    assert store.read_identifier_or_none(fixture["store"], "ade") is None
    players.revoke_player(config, player="ade")
    made = store.read_identifier_or_none(fixture["store"], "ade")
    assert made is not None
    # A player that is put back keeps the record for a second revoke.
    players.restore_player(config, player="ade", instant=NOW)
    players.revoke_player(config, player="ade")
    assert store.read_identifier_or_none(fixture["store"], "ade") == made


# -- the notice at sign-up and at a send --------------------------------


def _world(tmp_path, dev_only: bool):
    fixture = build_service_fixture(tmp_path, dev_only=dev_only)
    config = dataclasses.replace(fixture["service_config"], signup="open")
    app = create_app(config, operator_token=TOKEN, digester=QuickDigester(),
                     usual_passwords=frozenset())
    return fixture, config, app


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver", headers=ORIGIN)


def test_the_probe_names_the_notice_version(tmp_path) -> None:
    _fixture, _config, app = _world(tmp_path, dev_only=True)
    assert _client(app).get("/api/signup").json() \
        == {"open": True, "notice_version": notice.NOTICE_VERSION}


def test_the_web_app_holds_the_same_notice_version() -> None:
    # The text of the notice is in the web app. A change of the text is
    # a change of the two numbers together.
    import re

    source = Path("web/src/signin/notice.ts").read_text(encoding="utf-8")
    found = re.search(r"^export const NOTICE_VERSION = (\d+);$", source,
                      re.M)
    assert found is not None
    assert int(found.group(1)) == notice.NOTICE_VERSION


@pytest.mark.parametrize("agrees", [None, False, "true", 1])
def test_a_sign_up_with_no_agreement_makes_no_account(tmp_path,
                                                      agrees) -> None:
    fixture, _config, app = _world(tmp_path, dev_only=True)
    body = {"username": "alice", "password": GOOD}
    if agrees is not None:
        body["agrees_public"] = agrees
    answer = _client(app).post("/api/signup", json=body)
    assert answer.status_code == 400
    assert answer.json() == {"cause": "notice"}
    assert not store.any_player(fixture["store"])
    assert not (fixture["store"] / "names").exists()


def test_a_sign_up_writes_the_consent_record(tmp_path) -> None:
    fixture, _config, app = _world(tmp_path, dev_only=False)
    client = _client(app)
    assert client.post("/api/signup", json={
        "username": "alice", "password": GOOD,
        "agrees_public": True}).status_code == 201
    record = store.read_consent_or_none(fixture["store"], "alice", 1)
    assert record["player"] == "alice" and record["notice"] == 1
    assert client.get("/api/me").json()["notice"] \
        == {"version": 1, "agreed": True, "required": True}


def _player_with_session(fixture, config, app, name="bru") -> TestClient:
    """A stored player with a session and no consent record."""
    players.make_player(config, player=name, clock=lambda: FIXED_CLOCK)
    signin.claim_stored_names(fixture["store"], NOW)
    client = _client(app)
    from service import access

    value = access.open_session(fixture["store"], name, user_agent="test",
                                instant=datetime.datetime.now(datetime.UTC))
    client.cookies.set(auth.SESSION_COOKIE, value)
    return client


def test_a_send_with_no_agreement_writes_nothing(tmp_path) -> None:
    fixture, config, app = _world(tmp_path, dev_only=False)
    client = _player_with_session(fixture, config, app)
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    assert client.get("/api/me").json()["notice"] \
        == {"version": 1, "agreed": False, "required": True}
    refused = client.post(f"/api/submission?day={DAY}",
                          json=mixed_wire_record())
    assert refused.status_code == 409
    assert refused.content == b'{"cause":"notice"}'
    assert store.list_submissions(fixture["store"], DAY) == ()
    # The agreement names the version that the screen showed.
    stale = client.post("/api/account/consent", json={"notice": 7})
    assert stale.status_code == 409
    assert stale.content == b'{"cause":"notice-version"}'
    agreed = client.post("/api/account/consent", json={"notice": 1})
    assert agreed.json() == {"agreed": True, "notice": 1}
    assert client.post("/api/account/consent",
                       json={"notice": 1}).status_code == 200
    assert client.post(f"/api/submission?day={DAY}",
                       json=mixed_wire_record()).status_code == 200
    assert store.list_submissions(fixture["store"], DAY) == ("bru",)


def test_the_refusal_is_one_body_across_four_targets(tmp_path) -> None:
    bodies = set()
    for number, seed in enumerate("acde"):
        fixture, config, app = _world(tmp_path / f"w{number}",
                                      dev_only=False)
        client = _player_with_session(fixture, config, app)
        open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
                 pick_seed=seed * 32, secret="b" * 64)
        answer = client.post(f"/api/submission?day={DAY}",
                             json=mixed_wire_record())
        bodies.add((answer.status_code, answer.content))
        # Before a day is named too: the refusal reads no day.
        bodies.add((client.post("/api/submission").status_code,
                    client.post("/api/submission").content))
    assert bodies == {(409, b'{"cause":"notice"}')}


def test_a_development_pool_needs_no_agreement_for_a_send(tmp_path) -> None:
    fixture, config, app = _world(tmp_path, dev_only=True)
    client = _player_with_session(fixture, config, app)
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    assert client.get("/api/me").json()["notice"]["required"] is False
    assert client.post(f"/api/submission?day={DAY}",
                       json=mixed_wire_record()).status_code == 200


def test_the_consent_path_wants_a_session_and_the_origin(tmp_path) -> None:
    fixture, config, app = _world(tmp_path, dev_only=False)
    assert _client(app).post("/api/account/consent",
                             json={"notice": 1}).status_code == 401
    client = _player_with_session(fixture, config, app)
    bare = TestClient(app, base_url="https://testserver")
    bare.cookies.set(auth.SESSION_COOKIE,
                     client.cookies.get(auth.SESSION_COOKIE))
    assert bare.post("/api/account/consent",
                     json={"notice": 1}).status_code == 403
    assert not notice.agreed(fixture["store"], "bru")


# -- the start ----------------------------------------------------------


def test_the_start_writes_one_time_and_answers_one_body(
        tmp_path, monkeypatch) -> None:
    from service import server

    fixture, config, app = _world(tmp_path, dev_only=False)
    client = _player_with_session(fixture, config, app)
    root = fixture["store"]
    # No day: the same answer, and no record.
    bodies = {client.post("/api/day/start").content}
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    monkeypatch.setattr(server, "utc_now", lambda: NOW)
    first = client.post("/api/day/start")
    assert first.status_code == 200
    bodies.add(first.content)
    assert store.read_start_or_none(root, DAY, "bru") == NOW.isoformat()
    monkeypatch.setattr(server, "utc_now",
                        lambda: NOW + datetime.timedelta(minutes=9))
    bodies.add(client.post("/api/day/start").content)
    assert store.read_start_or_none(root, DAY, "bru") == NOW.isoformat()
    # A day that is not open: the same answer, and no new record.
    from service.day import close_day

    close_day(config, clock=lambda: FIXED_CLOCK)
    other = _player_with_session(fixture, config, app, name="cyd")
    bodies.add(other.post("/api/day/start").content)
    assert store.read_start_or_none(root, DAY, "cyd") is None
    assert bodies == {b'{"ok":true}'}
    assert _client(app).post("/api/day/start").status_code == 401


def test_the_start_needs_no_agreement_and_is_not_a_send(tmp_path) -> None:
    fixture, config, app = _world(tmp_path, dev_only=False)
    client = _player_with_session(fixture, config, app)
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    assert client.post("/api/day/start").status_code == 200
    assert store.list_submissions(fixture["store"], DAY) == ()
    assert client.get("/api/day").json()["submitted"] is False


# -- the address of the snapshots ---------------------------------------


def test_the_about_answer_names_the_public_data_address(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(
        fixture["service_config"],
        public_data_url="https://data.example.org/starvector")
    client = TestClient(create_app(config))
    assert client.get("/api/about").json()["public_data_url"] \
        == "https://data.example.org/starvector"


def test_the_config_checks_the_public_data_address() -> None:
    base = {"config_version": 1, "player": "ade", "scoring_config": "x",
            "data_root": "data", "store_root": "store", "port": 8000}
    assert parse_service_config(base, "t").public_data_url is None
    good = parse_service_config(
        {**base, "public_data_url": "https://example.org/d"}, "t")
    assert good.public_data_url == "https://example.org/d"
    for bad in ("example.org", 7, "ftp://example.org"):
        with pytest.raises(ServiceConfigError):
            parse_service_config({**base, "public_data_url": bad}, "t")
