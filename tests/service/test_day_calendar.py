"""Unit and integration: the day calendar and the closing status.

Spec BR1 (docs/specs/beta-readiness.md) section 3: the UTC label
rule, the close instant, the open sequence, and the "closing" status
that stops a send while the close scores.
"""

import dataclasses
import datetime

import pytest
from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import schedule, store
from service.day import close_day, open_day, rescore_days, reveal_day
from service.server import create_app

UTC = datetime.UTC


def _at(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text).replace(tzinfo=UTC)


# -- the pure calendar -------------------------------------------------


@pytest.mark.parametrize(("hour", "instant", "label"), [
    # A late rollover: the label is the date on which the day closes.
    ("22:00", "2026-09-24T21:59:59", "2026-09-24"),
    ("22:00", "2026-09-24T22:00:00", "2026-09-25"),
    ("22:00", "2026-09-24T00:30:00", "2026-09-24"),
    # Midnight: the label is the full UTC date.
    ("00:00", "2026-09-24T00:00:00", "2026-09-24"),
    ("00:00", "2026-09-24T23:59:59", "2026-09-24"),
    # A rollover before noon: the label is the date on which the day
    # opens.
    ("06:00", "2026-09-24T05:59:59", "2026-09-23"),
    ("06:00", "2026-09-24T06:00:00", "2026-09-24"),
    # Noon goes with the late side.
    ("12:00", "2026-09-24T11:59:59", "2026-09-24"),
    ("12:00", "2026-09-24T12:00:00", "2026-09-25"),
    # No hour: the development flow reads the UTC date.
    (None, "2026-09-24T23:30:00", "2026-09-24"),
])
def test_the_label_is_the_date_with_most_of_the_window(hour, instant,
                                                       label) -> None:
    assert schedule.label_at(_at(instant), hour) == label


@pytest.mark.parametrize(("hour", "label", "closes"), [
    ("22:00", "2026-09-24", "2026-09-24T22:00:00+00:00"),
    ("00:00", "2026-09-24", "2026-09-25T00:00:00+00:00"),
    ("06:30", "2026-09-24", "2026-09-25T06:30:00+00:00"),
    ("12:00", "2026-12-31", "2026-12-31T12:00:00+00:00"),
    ("00:00", "2026-12-31", "2027-01-01T00:00:00+00:00"),
])
def test_the_close_instant_ends_the_labeled_window(hour, label,
                                                   closes) -> None:
    assert schedule.closes_at_text(label, hour) == closes
    moment = schedule.closes_at_for(label, hour)
    # The window holds its own label until the close instant, and the
    # close instant starts the next label.
    assert schedule.label_at(moment - datetime.timedelta(seconds=1),
                             hour) == label
    following = (datetime.date.fromisoformat(label)
                 + datetime.timedelta(days=1)).isoformat()
    assert schedule.label_at(moment, hour) == following


def test_a_late_hour_keeps_the_wire_string_it_had() -> None:
    # The day view served f"{day}T{hour}:00+00:00" before BR1, and a
    # late hour keeps it byte for byte.
    assert schedule.closes_at_text("2026-08-12", "22:00") \
        == "2026-08-12T22:00:00+00:00"


def test_the_next_label_follows_the_latest_day() -> None:
    hour = "22:00"
    # The rollover at 22:00 on the 24th closes day 24 and opens 25.
    assert schedule.next_open_label(
        "2026-09-24", _at("2026-09-24T22:00:05"), hour) == "2026-09-25"
    # A close and reveal at 20:00, before the hour, opens the next
    # label before its window.
    assert schedule.next_open_label(
        "2026-09-24", _at("2026-09-24T20:00:00"), hour) == "2026-09-25"
    # A box that was down for two days opens the current label.
    assert schedule.next_open_label(
        "2026-09-20", _at("2026-09-24T10:00:00"), hour) == "2026-09-24"
    assert schedule.next_open_label(
        None, _at("2026-09-24T10:00:00"), hour) == "2026-09-24"


def test_a_label_ahead_of_the_calendar_refuses_with_an_hour() -> None:
    instant = _at("2026-09-24T10:00:00")
    schedule.check_open_label("2026-09-25", instant, "22:00")
    with pytest.raises(schedule.ScheduleError, match="ahead of the"):
        schedule.check_open_label("2026-09-26", instant, "22:00")
    # With no hour the development flow opens days back to back.
    schedule.check_open_label("2030-01-01", instant, None)


@pytest.mark.parametrize("bad", ["24:00", "7:00", "07:60", "0700", "",
                                 "07:00\n", None, 7])
def test_a_bad_hour_refuses(bad) -> None:
    with pytest.raises(schedule.ScheduleError):
        schedule.rollover_minutes(bad)


def test_a_bad_label_and_a_naive_instant_refuse() -> None:
    with pytest.raises(schedule.ScheduleError):
        schedule.parse_label("2026-02-30")
    with pytest.raises(schedule.ScheduleError):
        schedule.parse_label("2026-9-4")
    with pytest.raises(schedule.ScheduleError, match="no time zone"):
        schedule.label_at(datetime.datetime(2026, 9, 24), "22:00")


def test_due_is_the_close_instant_and_after() -> None:
    assert not schedule.is_due("2026-09-24", _at("2026-09-24T21:59:59"),
                               "22:00")
    assert schedule.is_due("2026-09-24", _at("2026-09-24T22:00:00"),
                           "22:00")


# -- the store and the lifecycle ---------------------------------------


DAY = "2026-08-12"


def _open(fixture, date=DAY, config=None):
    return open_day(config or fixture["service_config"], date=date,
                    clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
                    secret="b" * 64)


def _submit(fixture, day=DAY, player="ade"):
    store.write_once_json(
        store.submission_path(fixture["store"], day, player),
        {"day": day, "player": player, "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})


def test_a_move_to_closing_keeps_the_timestamps(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    moved = store.update_day_status(fixture["store"], DAY,
                                    expect_status="open",
                                    new_status="closing",
                                    timestamp_field=None, timestamp=None)
    assert moved.status == "closing"
    assert moved.closed_at is None and moved.revealed_at is None
    assert store.read_day_record(fixture["store"], DAY) == moved
    with pytest.raises(store.StoreError, match="no timestamp field"):
        store.update_day_status(fixture["store"], DAY,
                                expect_status="closing",
                                new_status="closed",
                                timestamp_field=None, timestamp=FIXED_CLOCK)


def test_the_close_passes_through_closing(tmp_path, monkeypatch) -> None:
    from service import day as day_module

    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    _submit(fixture)
    seen: list[str] = []
    original = day_module.harness.prewarm_records

    def watching(*arguments, **keywords):
        seen.append(store.read_day_record(fixture["store"], DAY).status)
        return original(*arguments, **keywords)

    monkeypatch.setattr(day_module.harness, "prewarm_records", watching)
    count = close_day(fixture["service_config"], date=DAY,
                      providers=fixture["providers"],
                      clock=lambda: FIXED_CLOCK)
    assert count == 1
    # The encode ran while the day was in "closing".
    assert seen == ["closing"]
    assert store.read_day_record(fixture["store"], DAY).status == "closed"


def test_a_stopped_close_continues_from_closing(tmp_path,
                                                monkeypatch) -> None:
    from service import day as day_module

    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    _submit(fixture)

    def stopping(*_arguments, **_keywords):
        raise RuntimeError("the provider stopped answering")

    monkeypatch.setattr(day_module.harness, "prewarm_records", stopping)
    with pytest.raises(RuntimeError, match="stopped answering"):
        close_day(fixture["service_config"], date=DAY,
                  providers=fixture["providers"], clock=lambda: FIXED_CLOCK)
    assert store.read_day_record(fixture["store"], DAY).status == "closing"
    # Rescore does not read a half-closed day.
    counts = rescore_days(fixture["service_config"],
                          config_path=fixture["scoring_config_path"],
                          providers=fixture["providers"])
    assert counts["skipped_open"] == 1 and counts["days"] == 0
    monkeypatch.undo()
    count = close_day(fixture["service_config"], date=DAY,
                      providers=fixture["providers"],
                      clock=lambda: FIXED_CLOCK)
    assert count == 1
    assert store.read_day_record(fixture["store"], DAY).status == "closed"


def test_a_missing_key_refuses_while_the_day_is_open(tmp_path,
                                                    monkeypatch) -> None:
    from service import day as day_module

    fixture = build_service_fixture(tmp_path)
    _open(fixture)

    def no_key(*_arguments, **_keywords):
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    # The wiring builds the provider clients, and a missing key stops
    # it. The day must continue to accept sends: nothing moved it.
    monkeypatch.setattr(day_module.scoring, "wire_for_close", no_key)
    with pytest.raises(RuntimeError, match="not set"):
        close_day(fixture["service_config"], date=DAY,
                  clock=lambda: FIXED_CLOCK)
    assert store.read_day_record(fixture["store"], DAY).status == "open"


def test_open_waits_for_the_reveal(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    with pytest.raises(store.StoreError, match="reveal it before"):
        _open(fixture, date="2026-08-13")
    close_day(fixture["service_config"], date=DAY,
              providers=fixture["providers"], clock=lambda: FIXED_CLOCK)
    with pytest.raises(store.StoreError, match="reveal it before"):
        _open(fixture, date="2026-08-13")
    reveal_day(fixture["service_config"], date=DAY,
               clock=lambda: FIXED_CLOCK)
    with pytest.raises(store.StoreError, match="not after the latest"):
        _open(fixture, date="2026-08-11")
    assert _open(fixture, date="2026-08-13").status == "open"


def test_open_with_an_hour_refuses_a_label_ahead(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc="22:00")
    with pytest.raises(store.StoreError, match="ahead of the"):
        open_day(config, date="2026-09-27", clock=lambda: FIXED_CLOCK,
                 now=lambda: _at("2026-09-24T10:00:00"))
    record = open_day(config, clock=lambda: FIXED_CLOCK,
                      now=lambda: _at("2026-09-24T22:00:01"))
    assert record.day == "2026-09-25"


def _app_world(tmp_path, *, hour=None):
    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc=hour)
    return fixture, config, TestClient(create_app(config))


def test_a_send_meets_a_closing_day_with_a_constant_refusal(
        tmp_path) -> None:
    fixture, _config, client = _app_world(tmp_path)
    _open(fixture)
    store.update_day_status(fixture["store"], DAY, expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)
    answer = client.post("/api/submission", json=mixed_wire_record())
    assert answer.status_code == 409
    assert answer.json() == {"cause": "day-closed"}
    assert client.get("/api/day").json()["status"] == "closing"
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_a_send_that_races_the_close_refuses(tmp_path,
                                             monkeypatch) -> None:
    """The race of the plan document, 5.2 item 1: a send during the
    encode."""
    from service import day as day_module

    fixture, _config, client = _app_world(tmp_path)
    _open(fixture)
    _submit(fixture, player="bru")
    answers = []
    original = day_module.harness.prewarm_records

    def sending_during_the_encode(*arguments, **keywords):
        answers.append(client.post("/api/submission",
                                   json=mixed_wire_record()))
        return original(*arguments, **keywords)

    monkeypatch.setattr(day_module.harness, "prewarm_records",
                        sending_during_the_encode)
    closed = client.post("/api/day/close")
    assert closed.status_code == 200 and closed.json() == {"trial_rows": 1}
    assert [answer.status_code for answer in answers] == [409]
    assert answers[0].json() == {"cause": "day-closed"}
    # Each stored submission has its row: nothing slipped between.
    root = fixture["store"]
    assert store.list_submissions(root, DAY) == ("bru",)
    assert store.trial_row_path(root, DAY, "bru").is_file()


def test_the_open_endpoint_uses_the_calendar(tmp_path, monkeypatch) -> None:
    from service import day as day_module

    fixture, _config, client = _app_world(tmp_path, hour="22:00")
    monkeypatch.setattr(day_module, "utc_now",
                        lambda: _at("2026-09-24T09:00:00"))
    opened = client.post("/api/day/open")
    assert opened.status_code == 200 and opened.json()["day"] == "2026-09-24"
    view = client.get("/api/day").json()
    assert view["closes_at"] == "2026-09-24T22:00:00+00:00"
    # An open day refuses a second open, and so does a closed one.
    assert client.post("/api/day/open").status_code == 409
    assert client.post("/api/day/close").status_code == 200
    refused = client.post("/api/day/open")
    assert refused.status_code == 409
    assert "reveal it before" in refused.json()["detail"]
    assert client.post("/api/day/reveal").status_code == 200
    # A close and reveal before the hour opens the next label.
    reopened = client.post("/api/day/open")
    assert reopened.json()["day"] == "2026-09-25"


def test_an_early_hour_serves_the_next_date_as_the_close(tmp_path) -> None:
    fixture, _config, client = _app_world(tmp_path, hour="00:00")
    _open(fixture)
    assert client.get("/api/day").json()["closes_at"] \
        == "2026-08-13T00:00:00+00:00"


def test_the_write_lock_file_stays_out_of_the_listings(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    _open(fixture)
    with store.day_write_lock(fixture["store"], DAY):
        pass
    assert store.list_days(fixture["store"]) == (DAY,)
    assert store.list_submissions(fixture["store"], DAY) == ()


def test_write_once_leaves_no_temporary_file(tmp_path) -> None:
    target = tmp_path / "one" / "row.json"
    store.write_once_json(target, {"a": 1})
    with pytest.raises(store.StoreError, match="one-write"):
        store.write_once_json(target, {"a": 2})
    assert sorted(path.name for path in target.parent.iterdir()) \
        == ["row.json"]
    assert target.read_text(encoding="utf-8") == '{\n  "a": 1\n}\n'
