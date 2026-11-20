"""The proof of work at sign-up (spec PW1), through the server.

The challenge path, the check of a payload, the ledger of spent
proofs, and the values of the decisions. The tests use the cheap
settings of svc_fixture: a challenge solves in eight tries at most.
"""

import base64
import dataclasses
import datetime
import json

import altcha
import pytest
from fastapi.testclient import TestClient

from svc_fixture import (QUICK_PROOF, QUICK_PROOF_KEYS, QuickDigester,
                         build_service_fixture, solved_proof)

from service import proofs, store
from service import server as server_module
from service.server import create_app

OPERATOR_TOKEN = "test-operator-token"
GOOD = "correct horse battery"
ORIGIN = {"origin": "https://testserver"}


def _world(tmp_path, signup: str = "open"):
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"], signup=signup)
    app = create_app(config, operator_token=OPERATOR_TOKEN,
                     digester=QuickDigester(), usual_passwords=frozenset(),
                     proof_keys=QUICK_PROOF_KEYS, proof_settings=QUICK_PROOF)
    return fixture, app


def _client(app) -> TestClient:
    return TestClient(app, base_url="https://testserver", headers=ORIGIN)


def _sign_up(client, name: str, proof: object):
    body = {"username": name, "password": GOOD, "agrees_public": True}
    if proof is not None:
        body["proof"] = proof
    return client.post("/api/signup", json=body)


def _parts(payload: str) -> dict:
    return json.loads(base64.b64decode(payload))


def _encode(parts: dict) -> str:
    return base64.b64encode(json.dumps(parts).encode()).decode()


def test_the_challenge_path_follows_the_switch(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    answer = _client(app).get("/api/signup/challenge")
    assert answer.status_code == 200
    assert answer.headers["cache-control"] == "no-store"
    parameters = answer.json()["parameters"]
    assert parameters["algorithm"] == "PBKDF2/SHA-256"
    assert parameters["cost"] == QUICK_PROOF.cost
    assert "keySignature" in parameters
    assert isinstance(answer.json()["signature"], str)
    _closed_fixture, closed = _world(tmp_path / "closed", signup="closed")
    probe = _client(closed).get("/api/signup")
    refused = _client(closed).get("/api/signup/challenge")
    assert refused.status_code == 404
    assert refused.content == probe.content


def test_each_challenge_is_new(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    client = _client(app)
    first = client.get("/api/signup/challenge").json()
    second = client.get("/api/signup/challenge").json()
    assert first["parameters"]["nonce"] != second["parameters"]["nonce"]
    assert first["signature"] != second["signature"]


def test_a_challenge_ends_at_its_lifetime(tmp_path, monkeypatch) -> None:
    _fixture, app = _world(tmp_path)
    instant = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.UTC)
    monkeypatch.setattr(server_module, "utc_now", lambda: instant)
    parameters = _client(app).get("/api/signup/challenge").json()[
        "parameters"]
    assert parameters["expiresAt"] \
        == int(instant.timestamp()) + QUICK_PROOF.lifetime_seconds


def test_a_solved_challenge_makes_an_account(tmp_path) -> None:
    fixture, app = _world(tmp_path)
    client = _client(app)
    assert _sign_up(client, "alice", solved_proof(client)).status_code == 201
    assert store.any_player(fixture["store"])


@pytest.mark.parametrize("proof", [
    None, "", 7, ["a"], {"challenge": {}}, "not base64 at all!",
    base64.b64encode(b"[1, 2]").decode(),
    base64.b64encode(b'{"challenge": 1, "solution": 2}').decode(),
    "A" * (proofs.PAYLOAD_MAX_CHARS + 4),
])
def test_a_sign_up_with_no_good_proof_makes_no_account(tmp_path,
                                                       proof) -> None:
    fixture, app = _world(tmp_path)
    answer = _sign_up(_client(app), "alice", proof)
    assert answer.status_code == 400
    assert answer.json() == {"cause": "proof"}
    assert "set-cookie" not in answer.headers
    assert not store.any_player(fixture["store"])


def test_a_challenge_of_a_different_key_does_not_agree(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    stranger = proofs.keys_from_secret("a different key")
    challenge = altcha.Challenge.from_dict(proofs.make_challenge(
        stranger, QUICK_PROOF, datetime.datetime.now(datetime.UTC)))
    payload = altcha.Payload(challenge,
                             altcha.solve_challenge(challenge)).to_base64()
    answer = _sign_up(_client(app), "alice", payload)
    assert answer.json() == {"cause": "proof"}


def test_a_changed_payload_does_not_agree(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    client = _client(app)
    parts = _parts(solved_proof(client))
    key = parts["solution"]["derivedKey"]
    wrong_key = {**parts, "solution": {
        **parts["solution"],
        "derivedKey": ("0" if key[0] != "0" else "1") + key[1:]}}
    assert _sign_up(client, "alice", _encode(wrong_key)).json() \
        == {"cause": "proof"}
    # A longer life in the parameters breaks the signature.
    longer = json.loads(json.dumps(parts))
    longer["challenge"]["parameters"]["expiresAt"] += 3600
    assert _sign_up(client, "alice", _encode(longer)).json() \
        == {"cause": "proof"}
    # A challenge with no key signature also breaks the signature.
    bare = json.loads(json.dumps(parts))
    del bare["challenge"]["parameters"]["keySignature"]
    assert _sign_up(client, "alice", _encode(bare)).json() \
        == {"cause": "proof"}


def test_a_proof_after_its_end_does_not_agree(tmp_path, monkeypatch) -> None:
    fixture, app = _world(tmp_path)
    client = _client(app)
    payload = solved_proof(client)
    later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(
        seconds=QUICK_PROOF.lifetime_seconds + 1)
    monkeypatch.setattr(server_module, "utc_now", lambda: later)
    assert _sign_up(client, "alice", payload).json() == {"cause": "proof"}
    assert not store.any_player(fixture["store"])


def test_one_proof_makes_one_account(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    client = _client(app)
    payload = solved_proof(client)
    assert _sign_up(client, "alice", payload).status_code == 201
    again = _sign_up(_client(app), "bobby", payload)
    assert again.status_code == 400
    assert again.json() == {"cause": "proof"}


def test_a_refused_sign_up_gives_the_proof_back(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    client = _client(app)
    payload = solved_proof(client)
    assert _sign_up(client, "al", payload).json() == {"cause": "name-rule"}
    assert _sign_up(client, "admin", payload).json() \
        == {"cause": "name-reserved"}
    assert _sign_up(client, "alice", payload).status_code == 201
    taken = _sign_up(_client(app), "alice", solved_proof(client))
    assert taken.status_code == 409


def test_the_cap_comes_before_the_proof(tmp_path) -> None:
    _fixture, app = _world(tmp_path)
    client = _client(app)
    for number in range(10):
        assert _sign_up(client, f"player-{number}",
                        solved_proof(client)).status_code == 201
    # A capped address gets the cap, with or without a proof.
    assert _sign_up(client, "one-more", None).status_code == 429


def test_the_ledger_forgets_a_proof_at_its_end() -> None:
    ledger = proofs.SpentProofs()
    start = datetime.datetime(2026, 11, 19, tzinfo=datetime.UTC)
    proof = proofs.Proof(signature="s", expires_at=int(start.timestamp())
                         + 60)
    assert ledger.hold(proof, start)
    assert not ledger.hold(proof, start)
    ledger.give_back(proof)
    assert ledger.hold(proof, start)
    after = start + datetime.timedelta(seconds=61)
    assert ledger.hold(proof, after)


def test_the_keys_of_a_secret() -> None:
    assert proofs.keys_from_secret(None) is None
    assert proofs.keys_from_secret("") is None
    one = proofs.keys_from_secret("one")
    assert one == proofs.keys_from_secret("one")
    assert one.challenge != one.derived
    assert one != proofs.keys_from_secret("two")


def test_the_values_of_the_decisions() -> None:
    assert proofs.ALGORITHM == "PBKDF2/SHA-256"
    assert proofs.DEPLOYED == proofs.ProofSettings(
        cost=5_000, counter_low=5_000, counter_high=10_000,
        lifetime_seconds=600)
    assert proofs.KEY_ENVIRONMENT_NAME == "STARVECTOR_ALTCHA_KEY"
    assert proofs.PAYLOAD_MAX_CHARS == 4_096


def test_a_payload_of_the_deployed_settings_is_short() -> None:
    # Decision D10: the cap is four times the length of a payload.
    keys = proofs.keys_from_secret("length")
    settings = dataclasses.replace(proofs.DEPLOYED, cost=1, counter_low=0,
                                   counter_high=1)
    challenge = altcha.Challenge.from_dict(proofs.make_challenge(
        keys, settings, datetime.datetime.now(datetime.UTC)))
    solution = altcha.solve_challenge(challenge)
    solution.time = 123456.789
    payload = altcha.Payload(challenge, solution).to_base64()
    assert len(payload) < 1_000
