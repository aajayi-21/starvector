"""Spec CR1: whitespace text, the blind run, and the automatic skip."""

from fastapi.testclient import TestClient
from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from core import atoms
from service import limits
from service.day import open_day
from service.server import create_app

DAY = "2026-08-12"


def _world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    return fixture, TestClient(create_app(fixture["service_config"]))


def test_the_whitespace_set_is_the_one_atoms_pins() -> None:
    assert limits.ASCII_WHITESPACE == atoms._ASCII_WHITESPACE


def test_whitespace_text_refuses_and_an_empty_label_does_not() -> None:
    record = mixed_wire_record()
    assert limits.blank_text_refusal(record) is None
    spaces = {**record, "impressions": ["a ridge", "   "]}
    assert "impressions[1]" in limits.blank_text_refusal(spaces)
    groups = [dict(group) for group in record["groups"]]
    groups[0]["label"] = "\t"
    assert "groups[0].label" in limits.blank_text_refusal(
        {**record, "groups": groups})
    groups[0]["label"] = ""
    assert limits.blank_text_refusal({**record, "groups": groups}) is None
    assert limits.blank_text_refusal("not a record") is None


def test_the_send_refuses_whitespace_text(tmp_path) -> None:
    _, client = _world(tmp_path)
    record = {**mixed_wire_record(), "impressions": [" \n "]}
    answer = client.post(f"/api/submission?day={DAY}", json=record)
    assert answer.status_code == 400
    assert answer.json()["cause"] == "blank-text"
    good = client.post(f"/api/submission?day={DAY}",
                       json=mixed_wire_record())
    assert good.status_code == 200


# ---- the blind run, the guard, and the record ----

import datetime  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from svc_fixture import make_vp1  # noqa: E402

from providers.fake.text_encoder import REFUSAL_MARKER  # noqa: E402
from service import store  # noqa: E402
from service.day import (FAST_RETRY_PAUSES, CloseHeld,  # noqa: E402
                         close_day, quarantine_send)


def _record(index: int, refused: bool = False) -> dict:
    text = f"{REFUSAL_MARKER} {index}" if refused else f"a ridge {index}"
    return {**mixed_wire_record(), "impressions": [text, "cold air"]}


def _send(root: Path, player: str, record: dict) -> None:
    store.write_once_json(
        store.submission_path(root, DAY, player),
        {"day": DAY, "player": player, "trial_id": f"{len(player):032d}",
         "received_at": FIXED_CLOCK, "record": record})


def _day_of(tmp_path, good: int, refused: int):
    fixture, _ = _world(tmp_path)
    for index in range(good):
        _send(fixture["store"], f"good-{index:02d}", _record(index))
    for index in range(refused):
        _send(fixture["store"], f"bad-{index:02d}", _record(index, True))
    return fixture


def _close(fixture, pauses: list | None = None, **kwargs):
    return close_day(fixture["service_config"],
                     providers=kwargs.pop("providers", fixture["providers"]),
                     clock=lambda: FIXED_CLOCK,
                     sleep=(pauses.append if pauses is not None
                            else lambda _: None), **kwargs)


def test_a_refused_send_is_retried_recorded_and_skipped(tmp_path) -> None:
    fixture = _day_of(tmp_path, good=20, refused=1)
    pauses: list[float] = []
    assert _close(fixture, pauses) == 20
    assert pauses == list(FAST_RETRY_PAUSES)
    root = fixture["store"]
    assert store.read_day_record(root, DAY).status == "closed"
    assert store.list_quarantined(root, DAY) == ("bad-00",)
    record = store.read_quarantine_or_none(root, DAY, "bad-00")
    assert record.decided_by == "close" and record.note is None
    assert record.tries == len(FAST_RETRY_PAUSES) + 1
    assert record.cause == "input-refused"
    assert record.submission_digest == store.submission_digest(
        root, DAY, "bad-00")
    assert not store.trial_row_path(root, DAY, "bad-00").is_file()
    # The send stays in the store, unchanged (Rule 4).
    assert "bad-00" in store.list_submissions(root, DAY)


def test_the_guard_holds_the_day_above_ten_percent(tmp_path) -> None:
    fixture = _day_of(tmp_path, good=17, refused=3)
    with pytest.raises(CloseHeld) as held:
        _close(fixture)
    for player in ("bad-00", "bad-01", "bad-02"):
        assert player in str(held.value)
    root = fixture["store"]
    assert store.read_day_record(root, DAY).status == "closing"
    assert store.list_quarantined(root, DAY) == ()


def test_the_operator_skips_a_held_send_and_the_close_finishes(
        tmp_path) -> None:
    fixture = _day_of(tmp_path, good=17, refused=3)
    with pytest.raises(CloseHeld):
        _close(fixture)
    config = fixture["service_config"]
    with pytest.raises(store.StoreError, match="scores in the blind run"):
        quarantine_send(config, date=DAY, player="good-00", note="test",
                        providers=fixture["providers"],
                        clock=lambda: FIXED_CLOCK)
    for player in ("bad-00", "bad-01", "bad-02"):
        record = quarantine_send(config, date=DAY, player=player,
                                 note="the provider refuses this text",
                                 providers=fixture["providers"],
                                 clock=lambda: FIXED_CLOCK)
        assert record.decided_by == "operator"
    assert _close(fixture) == 17
    assert store.read_day_record(fixture["store"], DAY).status == "closed"


def test_the_operator_command_wants_a_held_day_and_a_note(tmp_path) -> None:
    fixture = _day_of(tmp_path, good=2, refused=0)
    config = fixture["service_config"]
    with pytest.raises(store.StoreError, match="'closing'"):
        quarantine_send(config, date=DAY, player="good-00", note="x",
                        providers=fixture["providers"])


class _Hard:
    """A text encoder that fails for one text with an error that is not a
    refusal, in the manner of a timeout after the client's retries."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.config_hash = inner.config_hash

    def encode_texts(self, texts):
        if any(text.startswith("hard-fault") for text in texts):
            raise TimeoutError("the provider did not answer")
        return self._inner.encode_texts(texts)


def test_an_error_that_is_not_a_refusal_stops_the_close(tmp_path) -> None:
    fixture = _day_of(tmp_path, good=20, refused=0)
    _send(fixture["store"], "slow",
          {**mixed_wire_record(), "impressions": ["hard-fault one"]})
    providers = {**fixture["providers"],
                 "text_encoder": _Hard(fixture["providers"]["text_encoder"])}
    pauses: list[float] = []
    with pytest.raises(TimeoutError):
        _close(fixture, pauses, providers=providers)
    assert pauses == []
    root = fixture["store"]
    assert store.read_day_record(root, DAY).status == "closing"
    assert store.list_quarantined(root, DAY) == ()


def test_a_vp1_day_records_the_skip_before_its_pick(tmp_path,
                                                    monkeypatch) -> None:
    from service import server as server_module
    from service.beacon import FakeBeacon

    fixture = make_vp1(build_service_fixture(tmp_path), tmp_path)
    before = datetime.datetime(2026, 8, 12, 12, tzinfo=datetime.UTC)
    monkeypatch.setattr(server_module, "utc_now", lambda: before)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, now=lambda: before)
    root = fixture["store"]
    for index in range(20):
        _send(root, f"good-{index:02d}", _record(index))
    _send(root, "bad-00", _record(0, True))
    seen: list[tuple] = []

    class Watching(FakeBeacon):
        def answers(self, number):
            seen.append(store.list_quarantined(root, DAY))
            return super().answers(number)

    assert _close(fixture, beacon=Watching()) == 20
    assert seen and seen[0] == ("bad-00",)


def test_the_status_names_the_quarantine_count(tmp_path) -> None:
    from service.day import day_status_lines

    fixture = _day_of(tmp_path, good=20, refused=1)
    _close(fixture)
    assert "quarantined 1" in day_status_lines(fixture["service_config"])


# ---- what the player and the operator read (spec CR1 sections 7, 8) ----


def _revealed_day_with_a_skip(tmp_path):
    from service.day import reveal_day

    fixture = _day_of(tmp_path, good=20, refused=0)
    # The configured player of the fixture world is "ade": the refused
    # send is theirs, thus the player surfaces read it.
    _send(fixture["store"], "ade", _record(0, True))
    _close(fixture)
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    return fixture, TestClient(create_app(fixture["service_config"]))


def test_the_player_reads_a_skip_as_not_scored(tmp_path) -> None:
    fixture, client = _revealed_day_with_a_skip(tmp_path)
    reveal = client.get("/api/reveal").json()
    assert reveal["quarantined"] is True
    assert reveal["trial"] is None
    assert "note" not in json.dumps(reveal)
    history = client.get("/api/history").json()
    assert history["days"] == []
    assert [row["day"] for row in history["not_scored"]] == [DAY]
    assert history["skill"] is None
    # The send is stored, thus the streak holds (ruling D2).
    assert client.get("/api/me").json()["streak"] == 1


def test_the_index_and_the_public_file_hold_the_skip(tmp_path) -> None:
    import sqlite3

    from service import index

    fixture, _ = _revealed_day_with_a_skip(tmp_path)
    target = tmp_path / "index.sqlite"
    index.build(fixture["store"], target)
    with sqlite3.connect(target) as db:
        rows = db.execute(
            "SELECT day, player, decided_by FROM quarantined").fetchall()
    assert rows == [(DAY, "ade", "close")]
