"""Integration: the instant trial paths for accounts (spec IM1 IM1.6).

A world with the fake beacon, the fake encoders, and no player record:
the configured player is the caller. The result loop does not run on a
thread here. Each test calls one tick when it wants the results.
"""

import dataclasses
import datetime
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, build_service_fixture, make_vp1,
                         mixed_wire_record)

from service import instant, instant_store, limits, server
from service.beacon import BeaconUnavailable
from service.config import ServiceConfigError
from service.day import open_day
from service.instant_book import build_book
from service.pick_rule import instant_faults
from service.pulse import FAKE_CHAIN
from service.server import create_app

START = datetime.datetime(2026, 11, 23, 10, 0, 0, tzinfo=datetime.UTC)


class Clock:
    """A clock that a test moves."""

    def __init__(self, instant_: datetime.datetime = START) -> None:
        self.now = instant_

    def __call__(self) -> datetime.datetime:
        return self.now

    def forward(self, **step: float) -> None:
        self.now = self.now + datetime.timedelta(**step)


class HeldBeacon:
    """A fake source that has no pulse until a test gives it."""

    chain = FAKE_CHAIN

    def __init__(self) -> None:
        from service.beacon import FakeBeacon

        self._inner = FakeBeacon()
        self.given = False
        self.disagree = False

    def ready_at(self, number: int) -> int:
        return 0

    def answers(self, number: int) -> list[dict]:
        if not self.given:
            raise BeaconUnavailable("the pulse is not there")
        found = self._inner.answers(number)
        if self.disagree:
            found[1] = dict(found[1], signature="ab" * 32,
                            randomness=_sha_of_hex("ab" * 32))
        return found


def _sha_of_hex(text: str) -> str:
    import hashlib

    return hashlib.sha256(bytes.fromhex(text)).hexdigest()


def _world(tmp_path: Path, monkeypatch, *, mode: str = "accounts",
           day_cap: int = 400, source=None, offset=None):
    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    config = dataclasses.replace(fixture["service_config"], instant=mode,
                                 instant_day_cap=day_cap)
    clock = Clock()
    monkeypatch.setattr(server, "utc_now", clock)
    app = create_app(config, instant_source=source,
                     instant_clock_offset=offset)
    return fixture, TestClient(app), app, clock


def _start(client) -> dict:
    answer = client.post("/api/instant/start")
    assert answer.status_code == 200, answer.text
    return answer.json()


def _send(client, trial: dict, record: dict | None = None):
    return client.post(
        f"/api/instant/{trial['date']}/{trial['trial_id']}/send",
        json=record or mixed_wire_record())


def _played(client, app) -> tuple[dict, dict]:
    """One full trial: the start, the send, one tick, the result."""
    trial = _start(client)
    receipt = _send(client, trial)
    assert receipt.status_code == 200, receipt.text
    assert app.state.instant.tick() == 1
    result = client.get(f"/api/instant/{trial['date']}/{trial['trial_id']}")
    assert result.status_code == 200
    return trial, result.json()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_instant_off_gives_the_constant_404(tmp_path, monkeypatch) -> None:
    fixture, client, app, _ = _world(tmp_path, monkeypatch, mode="off",
                                     day_cap=None)
    assert app.state.instant is None
    for method, path in [("get", "/api/instant"),
                         ("post", "/api/instant/start"),
                         ("get", "/api/instant/head"),
                         ("get", "/api/instant/2026-11-23/" + "0" * 32),
                         ("post", "/api/instant/2026-11-23/" + "0" * 32
                          + "/send")]:
        answer = getattr(client, method)(path)
        assert answer.status_code == 404
        assert answer.content == b'{"detail":"not found"}'
    assert client.get("/api/about").json()["instant"] == "off"
    assert not (fixture["store"] / "instant").exists()


def test_instant_needs_the_pool_key(tmp_path) -> None:
    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    fixture["key_path"].unlink()
    config = dataclasses.replace(fixture["service_config"],
                                 instant="accounts", instant_day_cap=400)
    with pytest.raises(ServiceConfigError, match="pool key"):
        create_app(config)


def test_a_full_trial(tmp_path, monkeypatch) -> None:
    fixture, client, app, clock = _world(tmp_path, monkeypatch)
    trial = _start(client)
    assert trial["date"] == "2026-11-23"
    assert len(trial["trial_id"]) == 32
    clock.forward(seconds=42.5)
    receipt = _send(client, trial).json()
    # The pulse time is after the send time plus the margin.
    sent = clock.now.timestamp()
    assert receipt["pulse_time"] >= sent + instant.MARGIN_SECONDS
    assert receipt["chain_position"] == 0
    pending = client.get(
        f"/api/instant/{trial['date']}/{trial['trial_id']}").json()
    assert pending == {"status": "pending",
                       "beacon_round": receipt["beacon_round"],
                       "pulse_time": receipt["pulse_time"]}
    assert app.state.instant.tick() == 1
    result = client.get(
        f"/api/instant/{trial['date']}/{trial['trial_id']}").json()
    assert result["status"] == "settled"
    assert result["target_id"] in fixture["image_ids"]
    assert set(result["trial"]) == {"p", "decoy_count", "beaten", "tied",
                                    "target_rank"}
    assert 0.0 <= result["trial"]["p"] <= 1.0
    assert result["pick"]["commitment"] == receipt["commitment"]
    assert result["pick"]["send_digest"] == receipt["send_digest"]
    # No hit mark and no cutoff (rule I2).
    assert not any("hit" in name or "match" in name for name in result)


def test_the_pick_of_a_result_passes_the_check_of_a_reader(
        tmp_path, monkeypatch) -> None:
    _, client, app, _ = _world(tmp_path, monkeypatch)
    trial, result = _played(client, app)
    pick = result["pick"]
    assert instant_faults(
        trial_id=trial["trial_id"], send_digest=pick["send_digest"],
        commitment=pick["commitment"], nonce=pick["nonce"],
        signature=pick["beacon_signature"], randomness=pick["randomness"],
        target_id=result["target_id"], target_index=pick["target_index"],
        target_salt=pick["target_salt"], target_proof=pick["target_proof"],
        pool_count=pick["pool_count"], pool_root=pick["pool_root"]) == []


def test_the_photo_of_a_target_comes_after_the_result(
        tmp_path, monkeypatch) -> None:
    fixture, client, app, _ = _world(tmp_path, monkeypatch)
    for image_id in fixture["image_ids"]:
        assert client.get(f"/image/{image_id}").status_code == 404
    _, result = _played(client, app)
    assert client.get(f"/image/{result['target_id']}").status_code == 200
    others = [image_id for image_id in fixture["image_ids"]
              if image_id != result["target_id"]]
    assert all(client.get(f"/image/{image_id}").status_code == 404
               for image_id in others)


def test_nothing_before_the_pulse(tmp_path, monkeypatch) -> None:
    source = HeldBeacon()
    fixture, client, app, _ = _world(tmp_path, monkeypatch, source=source,
                                     offset=lambda: 0.0)
    trial = _start(client)
    receipt = _send(client, trial).json()
    path = f"/api/instant/{trial['date']}/{trial['trial_id']}"
    for _ in range(3):
        assert app.state.instant.tick() == 0
        assert client.get(path).json() == {
            "status": "pending", "beacon_round": receipt["beacon_round"],
            "pulse_time": receipt["pulse_time"]}
    directory = fixture["store"] / "instant" / trial["date"] \
        / trial["trial_id"]
    assert sorted(entry.name for entry in directory.iterdir()) == [
        "secret.json", "send.json", "start.json"]
    assert all(client.get(f"/image/{image_id}").status_code == 404
               for image_id in fixture["image_ids"])
    source.given = True
    assert app.state.instant.tick() == 1
    assert client.get(path).json()["status"] == "settled"


def test_the_nonce_is_in_no_answer_before_the_result(
        tmp_path, monkeypatch) -> None:
    source = HeldBeacon()
    fixture, client, app, _ = _world(tmp_path, monkeypatch, source=source,
                                     offset=lambda: 0.0)
    trial = _start(client)
    receipt = _send(client, trial)
    nonce = instant_store.read_secret_or_none(
        fixture["store"], trial["date"], trial["trial_id"])
    assert nonce is not None
    bodies = [receipt.text, client.get("/api/instant").text,
              client.get("/api/instant/head").text,
              client.get(f"/api/instant/{trial['date']}/"
                         f"{trial['trial_id']}").text]
    assert not any(nonce in body for body in bodies)


def test_two_sources_that_do_not_agree_keep_the_trial_pending(
        tmp_path, monkeypatch) -> None:
    source = HeldBeacon()
    source.given = source.disagree = True
    _, client, app, _ = _world(tmp_path, monkeypatch, source=source,
                               offset=lambda: 0.0)
    trial = _start(client)
    _send(client, trial)
    assert app.state.instant.tick() == 0
    path = f"/api/instant/{trial['date']}/{trial['trial_id']}"
    assert client.get(path).json()["status"] == "pending"
    source.disagree = False
    assert app.state.instant.tick() == 1


def test_one_trial_has_one_send(tmp_path, monkeypatch) -> None:
    fixture, client, _, _ = _world(tmp_path, monkeypatch)
    trial = _start(client)
    assert _send(client, trial).status_code == 200
    before = _snapshot(fixture["store"])
    second = _send(client, trial)
    assert second.status_code == 409
    assert second.json() == {"cause": "instant-sent"}
    assert _snapshot(fixture["store"]) == before


def test_a_second_start_gives_the_open_trial(tmp_path, monkeypatch) -> None:
    _, client, _, _ = _world(tmp_path, monkeypatch)
    first = _start(client)
    assert _start(client) == first
    assert client.get("/api/instant").json()["open"]["trial_id"] \
        == first["trial_id"]
    _send(client, first)
    assert client.get("/api/instant").json()["open"] is None
    assert _start(client)["trial_id"] != first["trial_id"]


def test_a_start_is_good_on_its_date_and_the_date_after(
        tmp_path, monkeypatch) -> None:
    fixture, client, _, clock = _world(tmp_path, monkeypatch)
    trial = _start(client)
    clock.forward(days=1)
    assert _start(client) == trial
    clock.forward(days=1)
    before = _snapshot(fixture["store"])
    late = _send(client, trial)
    assert late.status_code == 409
    assert late.json() == {"cause": "instant-expired"}
    assert _snapshot(fixture["store"]) == before
    assert _start(client)["trial_id"] != trial["trial_id"]


def test_a_trial_of_no_start_gives_the_constant_404(
        tmp_path, monkeypatch) -> None:
    _, client, _, _ = _world(tmp_path, monkeypatch)
    trial = _start(client)
    for date, trial_id in [("2026-11-23", "f" * 32),
                           ("2026-11-22", trial["trial_id"]),
                           ("not-a-date", trial["trial_id"]),
                           ("2026-11-23", "not-a-trial")]:
        for answer in (client.get(f"/api/instant/{date}/{trial_id}"),
                       client.post(f"/api/instant/{date}/{trial_id}/send",
                                   json=mixed_wire_record())):
            assert answer.status_code == 404
            assert answer.content == b'{"detail":"not found"}'


def test_the_cap_of_an_account_is_20_sends_on_one_date(
        tmp_path, monkeypatch) -> None:
    fixture, client, _, clock = _world(tmp_path, monkeypatch)
    for _ in range(limits.INSTANT_ACCOUNT_DAY_CAP):
        assert _send(client, _start(client)).status_code == 200
    view = client.get("/api/instant").json()
    assert view["sent_today"] == 20 and view["left_today"] == 0
    before = _snapshot(fixture["store"])
    refused = client.post("/api/instant/start")
    assert refused.status_code == 429
    assert refused.json() == {"cause": "instant-limit"}
    assert _snapshot(fixture["store"]) == before
    # The subsequent UTC date has a new allowance.
    clock.forward(days=1)
    assert client.get("/api/instant").json()["left_today"] == 20
    assert _send(client, _start(client)).status_code == 200


def test_a_send_at_the_cap_is_refused_before_the_encode(
        tmp_path, monkeypatch) -> None:
    fixture, client, _, _ = _world(tmp_path, monkeypatch, day_cap=2)
    held = []
    for _ in range(2):
        held.append(_start(client))
        assert _send(client, held[-1]).status_code == 200
    refused = client.post("/api/instant/start")
    assert refused.status_code == 503
    assert refused.json() == {"cause": "instant-full"}


def test_the_count_survives_a_start_of_the_server(
        tmp_path, monkeypatch) -> None:
    fixture, client, app, _ = _world(tmp_path, monkeypatch)
    trial, _ = _played(client, app)
    pending = _start(client)
    _send(client, pending)
    again = TestClient(create_app(
        dataclasses.replace(fixture["service_config"], instant="accounts",
                            instant_day_cap=400)))
    view = again.get("/api/instant").json()
    assert view["sent_today"] == 2
    assert view["record"]["sent"] == 2 and view["record"]["settled"] == 1
    assert again.get("/api/instant/head").json()["count"] == 2
    assert [row["status"] for row in view["trials"]] == ["pending",
                                                         "settled"]
    # The new server continues the send with no result.
    assert again.app.state.instant.tick() == 1
    assert again.get("/api/instant").json()["record"]["settled"] == 2


def test_the_clock_guard_refuses_a_send_and_stores_nothing(
        tmp_path, monkeypatch) -> None:
    offsets = [9.0]
    fixture, client, app, _ = _world(tmp_path, monkeypatch,
                                     offset=lambda: offsets[0])
    trial = _start(client)
    before = _snapshot(fixture["store"])
    refused = _send(client, trial)
    assert refused.status_code == 503
    assert refused.json() == {"cause": "clock"}
    assert _snapshot(fixture["store"]) == before
    offsets[0] = 0.5
    app.state.instant.measure()
    assert _send(client, trial).status_code == 200


def test_a_bad_record_is_refused_and_the_trial_stays_open(
        tmp_path, monkeypatch) -> None:
    fixture, client, _, _ = _world(tmp_path, monkeypatch)
    trial = _start(client)
    before = _snapshot(fixture["store"])
    refused = client.post(
        f"/api/instant/{trial['date']}/{trial['trial_id']}/send",
        json={"not": "a record"})
    assert refused.status_code == 400
    assert _snapshot(fixture["store"]) == before
    assert _send(client, trial).status_code == 200


def test_an_encoder_that_refuses_stores_nothing(tmp_path,
                                                monkeypatch) -> None:
    from service import settle

    fixture, client, _, _ = _world(tmp_path, monkeypatch)
    trial = _start(client)
    before = _snapshot(fixture["store"])

    def refuses(*_arguments, **_named):
        raise RuntimeError("the provider is down")

    monkeypatch.setattr(settle, "encode_submission", refuses)
    refused = _send(client, trial)
    assert refused.status_code == 503
    assert refused.json() == {"cause": "encoder"}
    assert _snapshot(fixture["store"]) == before
    monkeypatch.undo()
    monkeypatch.setattr(server, "utc_now", Clock())
    assert _send(client, trial).status_code == 200


def test_a_send_that_does_not_score_stays_pending(tmp_path,
                                                  monkeypatch) -> None:
    from service import scoring

    _, client, app, _ = _world(tmp_path, monkeypatch)
    trial = _start(client)
    _send(client, trial)
    real = scoring.score_stored_submission

    def refuses(*_arguments, **_named):
        raise RuntimeError("the provider is down")

    monkeypatch.setattr(scoring, "score_stored_submission", refuses)
    assert app.state.instant.tick() == 0
    path = f"/api/instant/{trial['date']}/{trial['trial_id']}"
    assert client.get(path).json()["status"] == "pending"
    monkeypatch.setattr(scoring, "score_stored_submission", real)
    assert app.state.instant.tick() == 1
    assert client.get(path).json()["status"] == "settled"


def test_the_chain_and_the_head(tmp_path, monkeypatch) -> None:
    fixture, client, _, clock = _world(tmp_path, monkeypatch)
    assert client.get("/api/instant/head").json() == {
        "count": 0, "position": None,
        "chain_link": instant.CHAIN_START, "received_at": None}
    receipts = []
    for _ in range(4):
        clock.forward(seconds=7)
        receipts.append(_send(client, _start(client)).json())
        head = client.get("/api/instant/head").json()
        assert head["chain_link"] == receipts[-1]["chain_link"]
        assert head["position"] == receipts[-1]["chain_position"]
    assert [row["chain_position"] for row in receipts] == [0, 1, 2, 3]
    # A new book reads the store and checks the chain.
    assert build_book(fixture["store"]).head().position == 3


def test_a_removed_send_stops_the_start_of_the_server(
        tmp_path, monkeypatch) -> None:
    from service.store import StoreError

    fixture, client, _, _ = _world(tmp_path, monkeypatch)
    trials = []
    for _ in range(3):
        trials.append(_start(client))
        _send(client, trials[-1])
    removed = fixture["store"] / "instant" / trials[1]["date"] \
        / trials[1]["trial_id"] / "send.json"
    removed.unlink()
    with pytest.raises(StoreError, match="chain"):
        build_book(fixture["store"])


def test_the_record_of_the_owner(tmp_path, monkeypatch) -> None:
    _, client, app, _ = _world(tmp_path, monkeypatch)
    empty = client.get("/api/instant").json()["record"]
    assert empty == {"sent": 0, "settled": 0, "mean_p": None,
                     "hit_number": None}
    scores = []
    for _ in range(3):
        _, result = _played(client, app)
        scores.append(result["trial"]["p"])
    record = client.get("/api/instant").json()["record"]
    assert record["sent"] == record["settled"] == 3
    assert record["mean_p"] == pytest.approx(sum(scores) / 3, abs=1e-6)
    assert record["hit_number"] > 0.0


def test_each_answer_is_the_same_for_two_targets_of_the_open_day(
        tmp_path, monkeypatch) -> None:
    """Rule I7 for the daily challenge: no instant byte follows the
    target of the open day (spec IM1 section 17)."""
    bodies = []
    for seed in ("a" * 32, "c" * 32):
        root = tmp_path / seed[:1]
        root.mkdir()
        fixture = make_vp1(build_service_fixture(root), root)
        commit = dataclasses.replace(
            fixture["service_config"], pick_protocol="commit-v1")
        open_day(commit, date="2026-11-23", clock=lambda: FIXED_CLOCK,
                 pick_seed=seed, secret="b" * 64)
        config = dataclasses.replace(commit, instant="accounts",
                                     instant_day_cap=400)
        monkeypatch.setattr(server, "utc_now", Clock())
        client = TestClient(create_app(config))
        found = [client.get("/api/instant").content,
                 client.get("/api/instant/head").content]
        trial = client.post("/api/instant/start").json()
        found.append(sorted(trial))
        receipt = _send(client, trial).json()
        found.append(sorted(receipt))
        found.append(client.get(
            f"/api/instant/{trial['date']}/{trial['trial_id']}").content)
        bodies.append(found)
    assert bodies[0][0] == bodies[1][0]
    assert bodies[0][1] == bodies[1][1]
    assert bodies[0][2:4] == bodies[1][2:4]
    # The pending body is a function of the send time alone.
    assert bodies[0][4] == bodies[1][4]


def test_the_stored_row_is_the_row_of_a_second_scoring(
        tmp_path, monkeypatch) -> None:
    """Rule I4: the stored send gives the stored row byte for byte."""
    from pipeline.config import load_scoring_config
    from service import scoring

    fixture, client, app, _ = _world(tmp_path, monkeypatch)
    trial, _ = _played(client, app)
    send = instant_store.read_send_or_none(
        fixture["store"], trial["date"], trial["trial_id"])
    result = instant_store.read_result_or_none(
        fixture["store"], trial["date"], trial["trial_id"])
    config = fixture["service_config"]
    wired = scoring.wire_for_close(
        load_scoring_config(Path(config.scoring_config)),
        config.scoring_config, Path(config.data_root))
    again, report = scoring.score_stored_submission(
        send.record, result.target_id, wired)
    row = scoring.instant_row_value(
        send.trial_id, again, report, wired,
        channel_scores=scoring.channel_score_values(
            send.record, result.target_id, wired))
    assert json.dumps(row, sort_keys=True) \
        == json.dumps(result.row, sort_keys=True)


TOKEN = "test-operator-token"
SECRETS = {"ade": "a" * 43, "bru": "b" * 43}


def _players_world(tmp_path: Path, monkeypatch, *, day_cap: int = 400,
                   dev_only: bool = True):
    """A world with two stored players, thus each caller has a session."""
    from svc_fixture import mint_player, plant_session

    fixture = make_vp1(build_service_fixture(tmp_path, dev_only=dev_only),
                       tmp_path)
    config = dataclasses.replace(fixture["service_config"],
                                 instant="accounts",
                                 instant_day_cap=day_cap)
    for name, secret in SECRETS.items():
        mint_player(config, player=name, display_name=name.title(),
                    clock=lambda: FIXED_CLOCK, secret=secret)
        plant_session(fixture["store"], f"{name}.{secret}")
    monkeypatch.setattr(server, "utc_now", Clock())
    return fixture, create_app(config, operator_token=TOKEN)


def _as(app, name: str | None) -> TestClient:
    from svc_fixture import pinned_session_value

    from service import auth

    client = TestClient(app)
    if name is not None:
        client.cookies.set(auth.SESSION_COOKIE, pinned_session_value(
            f"{name}.{SECRETS[name]}"))
    return client


def test_a_caller_with_no_session_gets_the_constant_401(
        tmp_path, monkeypatch) -> None:
    fixture, app = _players_world(tmp_path, monkeypatch)
    nobody = _as(app, None)
    before = _snapshot(fixture["store"])
    for method, path in [("get", "/api/instant"),
                         ("post", "/api/instant/start"),
                         ("get", "/api/instant/2026-11-23/" + "0" * 32),
                         ("post", "/api/instant/2026-11-23/" + "0" * 32
                          + "/send")]:
        answer = getattr(nobody, method)(path)
        assert answer.status_code == 401
        assert answer.content == b'{"detail":"unauthorized"}'
    assert _snapshot(fixture["store"]) == before
    # The head of the chain is for each reader.
    assert nobody.get("/api/instant/head").status_code == 200


def test_a_trial_is_for_its_owner_alone(tmp_path, monkeypatch) -> None:
    _, app = _players_world(tmp_path, monkeypatch)
    ade, bru = _as(app, "ade"), _as(app, "bru")
    trial = _start(ade)
    path = f"/api/instant/{trial['date']}/{trial['trial_id']}"
    assert bru.get(path).status_code == 404
    refused = bru.post(path + "/send", json=mixed_wire_record())
    assert refused.status_code == 404
    assert _send(ade, trial).status_code == 200
    assert app.state.instant.tick() == 1
    assert bru.get(path).status_code == 404
    assert ade.get(path).json()["status"] == "settled"
    # Each owner has its own record and its own allowance.
    assert ade.get("/api/instant").json()["record"]["sent"] == 1
    view = bru.get("/api/instant").json()
    assert view["record"]["sent"] == 0 and view["left_today"] == 20
    assert view["owner"] == "bru" and view["kind"] == "account"
    assert view["trials"] == []


def test_the_cap_of_all_owners_refuses_a_send_of_an_open_trial(
        tmp_path, monkeypatch) -> None:
    fixture, app = _players_world(tmp_path, monkeypatch, day_cap=1)
    ade, bru = _as(app, "ade"), _as(app, "bru")
    held = _start(ade)
    assert _send(bru, _start(bru)).status_code == 200
    before = _snapshot(fixture["store"])
    refused = _send(ade, held)
    assert refused.status_code == 503
    assert refused.json() == {"cause": "instant-full"}
    assert _snapshot(fixture["store"]) == before


def test_a_send_needs_the_agreement_to_the_notice(
        tmp_path, monkeypatch) -> None:
    from service import notice

    fixture, app = _players_world(tmp_path, monkeypatch, dev_only=False)
    ade = _as(app, "ade")
    before = _snapshot(fixture["store"])
    refused = ade.post("/api/instant/start")
    assert refused.status_code == 409
    assert refused.content == b'{"cause":"notice"}'
    assert _snapshot(fixture["store"]) == before
    notice.record_agreement(fixture["store"], "ade", START)
    trial = _start(ade)
    assert _send(ade, trial).status_code == 200
    send = instant_store.read_send_or_none(
        fixture["store"], trial["date"], trial["trial_id"])
    assert send.notice == notice.NOTICE_VERSION


def test_the_loop_thread_settles_a_send_with_no_read_of_the_owner(
        tmp_path, monkeypatch) -> None:
    import time

    fixture, client, app, _ = _world(tmp_path, monkeypatch)
    trial = _start(client)
    _send(client, trial)
    app.state.instant.start(pause_seconds=0.01)
    try:
        directory = fixture["store"] / "instant" / trial["date"] \
            / trial["trial_id"]
        deadline = time.monotonic() + 10.0
        while not (directory / "result.json").is_file():
            assert time.monotonic() < deadline, "the loop wrote no result"
            time.sleep(0.01)
    finally:
        app.state.instant.stop()
    assert client.get("/api/instant").json()["record"]["settled"] == 1


def test_a_clock_that_nobody_measured_refuses_and_is_tried_again(
        tmp_path, monkeypatch) -> None:
    from service import settle

    state = {"down": True}

    def offset() -> float:
        if state["down"]:
            raise OSError("no network")
        return 0.25

    _, client, app, clock = _world(tmp_path, monkeypatch, offset=offset)
    trial = _start(client)
    assert _send(client, trial).json() == {"cause": "clock"}
    state["down"] = False
    # The second try waits for the pause, thus a tick before it reads
    # no clock.
    clock.forward(seconds=settle.CLOCK_RETRY_SECONDS - 1)
    app.state.instant.tick()
    assert _send(client, trial).json() == {"cause": "clock"}
    clock.forward(seconds=2)
    app.state.instant.tick()
    assert app.state.instant.clock_offset == 0.25
    assert _send(client, trial).status_code == 200
