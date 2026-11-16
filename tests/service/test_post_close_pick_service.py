"""The pick after the close (spec VP1): open, gate, close, reveal."""

import datetime
import json

import pytest
from fastapi.testclient import TestClient
from svc_fixture import (FIXED_CLOCK, build_service_fixture, make_vp1,
                         mixed_wire_record)

from service import beacon as beacon_module
from service import pool_keys, store
from service import server as server_module
from service.beacon import (BeaconConfig, BeaconError, BeaconUnavailable,
                            FakeBeacon, fetch_pulse)
from service.day import close_day, open_day, pick_target, reveal_day
from service.pool_root import proof_agrees
from service.pulse import FAKE_CHAIN, pulse_time, randomness_of
from service.server import create_app

DAY = "2026-08-12"
# 00:00 UTC on the day after the label is the close of DAY.
CLOSES_AT = datetime.datetime(2026, 8, 13, 0, 0, tzinfo=datetime.UTC)
BEFORE_CLOSE = CLOSES_AT - datetime.timedelta(hours=1)


@pytest.fixture
def world(tmp_path, monkeypatch):
    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    monkeypatch.setattr(server_module, "utc_now", lambda: BEFORE_CLOSE)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, now=lambda: BEFORE_CLOSE)
    client = TestClient(create_app(fixture["service_config"]))
    return fixture, client


def _close(fixture, **kwargs):
    return close_day(fixture["service_config"],
                     providers=fixture["providers"],
                     clock=lambda: FIXED_CLOCK, **kwargs)


def test_the_open_stores_no_target_and_names_the_pulse(world) -> None:
    fixture, client = world
    record = store.read_day_record(fixture["store"], DAY)
    assert record.protocol == "vp1"
    assert (record.target_id, record.pick_seed, record.secret,
            record.commitment) == (None, None, None, None)
    margin = fixture["service_config"].beacon.margin_seconds
    assert int(CLOSES_AT.timestamp()) + margin \
        <= pulse_time(record.beacon_round, FAKE_CHAIN) \
        < int(CLOSES_AT.timestamp()) + margin + FAKE_CHAIN.period
    view = client.get("/api/day").json()
    assert view["protocol"] == "vp1"
    assert view["commitment"] is None
    assert view["beacon_round"] == record.beacon_round
    assert view["pool_root"] == record.pool_root
    assert "target_id" not in view


def test_the_open_refuses_a_pool_root_that_does_not_agree(tmp_path) -> None:
    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    path = pool_keys.root_file_path(fixture["pool_roots_dir"],
                                    fixture["preparation_version_id"])
    value = json.loads(path.read_text())
    value["pool_root"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(pool_keys.PoolKeyError):
        open_day(fixture["service_config"], date=DAY,
                 clock=lambda: FIXED_CLOCK, now=lambda: BEFORE_CLOSE)


def test_the_open_refuses_with_no_pool_key(tmp_path) -> None:
    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    fixture["key_path"].unlink()
    with pytest.raises(pool_keys.PoolKeyError):
        open_day(fixture["service_config"], date=DAY,
                 clock=lambda: FIXED_CLOCK, now=lambda: BEFORE_CLOSE)


def test_the_gate_reads_the_clock(world, monkeypatch) -> None:
    _, client = world
    monkeypatch.setattr(server_module, "utc_now",
                        lambda: CLOSES_AT - datetime.timedelta(seconds=1))
    assert client.post(f"/api/submission?day={DAY}",
                       json=mixed_wire_record()).status_code == 200


def test_a_send_at_the_close_instant_refuses(world, monkeypatch) -> None:
    fixture, client = world
    monkeypatch.setattr(server_module, "utc_now", lambda: CLOSES_AT)
    answer = client.post(f"/api/submission?day={DAY}",
                         json=mixed_wire_record())
    assert answer.status_code == 409
    assert answer.json()["cause"] == "day-closed"
    assert store.read_day_record(fixture["store"], DAY).status == "open"


def test_the_close_picks_from_the_pulse_and_proves_it(world) -> None:
    fixture, client = world
    assert client.post(f"/api/submission?day={DAY}",
                       json=mixed_wire_record()).status_code == 200
    assert _close(fixture) == 1
    record = store.read_day_record(fixture["store"], DAY)
    randomness = randomness_of(beacon_module.fake_signature(
        record.beacon_round))
    assert record.pick_seed == randomness
    assert record.target_id == pick_target(
        tuple(fixture["image_ids"]), DAY, randomness)
    assert proof_agrees(record.target_id, record.target_salt,
                        record.target_index, record.pool_count,
                        record.target_proof, record.pool_root)
    assert record.status == "closed"


def test_the_reveal_answer_holds_the_proof(world) -> None:
    fixture, client = world
    client.post(f"/api/submission?day={DAY}", json=mixed_wire_record())
    _close(fixture)
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    value = client.get("/api/reveal").json()
    assert value["protocol"] == "vp1"
    assert value["secret"] is None and value["commitment"] is None
    assert value["check"].startswith("uv run python tools/check_day.py")
    assert proof_agrees(value["target_id"], value["target_salt"],
                        value["target_index"], value["pool_count"],
                        value["target_proof"], value["pool_root"])
    assert randomness_of(value["beacon_signature"]) == value["randomness"]


class _Late:
    """A drand-like source: the pulse is at its time, not before."""

    chain = FAKE_CHAIN

    def __init__(self, unavailable: int = 0) -> None:
        self.calls = 0
        self.unavailable = unavailable

    def ready_at(self, number: int) -> int:
        return pulse_time(number, self.chain)

    def answers(self, number: int) -> list[dict]:
        self.calls += 1
        if self.calls <= self.unavailable:
            raise BeaconUnavailable("not yet")
        return FakeBeacon().answers(number)


def test_a_close_long_before_the_pulse_refuses(world) -> None:
    fixture, _ = world
    with pytest.raises(store.StoreError, match="close it at its scheduled"):
        _close(fixture, beacon=_Late(),
               now=lambda: BEFORE_CLOSE.timestamp())
    assert store.read_day_record(fixture["store"], DAY).status == "open"


def test_the_timer_close_at_the_instant_waits_for_the_pulse(world) -> None:
    fixture, _ = world
    source = _Late(unavailable=3)
    pauses = []
    _close(fixture, beacon=source, now=lambda: CLOSES_AT.timestamp(),
           sleep=pauses.append)
    assert source.calls == 4
    assert len(pauses) == 3
    assert store.read_day_record(fixture["store"], DAY).status == "closed"


def test_a_missing_pulse_leaves_the_day_closing(world) -> None:
    fixture, _ = world
    late = CLOSES_AT.timestamp() + 10_000
    with pytest.raises(BeaconError):
        _close(fixture, beacon=_Late(unavailable=10**6), now=lambda: late,
               sleep=lambda _: None)
    record = store.read_day_record(fixture["store"], DAY)
    assert record.status == "closing" and record.target_id is None
    # A subsequent close continues with the same pulse.
    _close(fixture, beacon=FakeBeacon())
    assert store.read_day_record(fixture["store"], DAY).status == "closed"


def test_sources_that_disagree_stop_the_close() -> None:
    class Split:
        chain = FAKE_CHAIN

        def answers(self, number):
            good = FakeBeacon().answers(number)
            other = beacon_module.fake_signature(number + 1)
            return [good[0], {**good[1], "signature": other,
                              "randomness": randomness_of(other)}]

    config = BeaconConfig(kind="fake", relays=())
    with pytest.raises(BeaconError, match="disagree"):
        fetch_pulse(Split(), 5, config, now=lambda: 0, sleep=lambda _: None)


def test_a_recorded_pick_does_not_change(world) -> None:
    fixture, _ = world
    _close(fixture)
    root = fixture["store"]
    record = store.read_day_record(root, DAY)
    with pytest.raises(store.StoreError):
        store.record_pick(root, DAY, target_id=record.target_id,
                          pick_seed="0" * 64,
                          beacon_signature=record.beacon_signature,
                          target_index=record.target_index,
                          target_salt=record.target_salt,
                          target_proof=record.target_proof)


def test_the_dev_rankings_refuse_before_the_pick(tmp_path, monkeypatch):
    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    monkeypatch.setattr(server_module, "utc_now", lambda: BEFORE_CLOSE)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, now=lambda: BEFORE_CLOSE)
    client = TestClient(create_app(fixture["service_config"],
                                   dev_mode=True))
    client.post(f"/api/submission?day={DAY}", json=mixed_wire_record())
    answer = client.get(f"/api/dev/rankings?day={DAY}")
    assert answer.status_code == 409
    assert answer.json()["cause"] == "no-target-yet"


def test_a_commit_v1_day_keeps_its_stored_form(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    raw = json.loads(store.day_record_path(fixture["store"], DAY)
                     .read_text())
    assert "protocol" not in raw
    record = store.read_day_record(fixture["store"], DAY)
    assert record.protocol == "commit-v1" and record.commitment


def test_the_results_index_builds_with_a_vp1_day(world, tmp_path) -> None:
    from service import index

    fixture, client = world
    client.post(f"/api/submission?day={DAY}", json=mixed_wire_record())
    _close(fixture)
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    index.build(fixture["store"], tmp_path / "index.sqlite")
