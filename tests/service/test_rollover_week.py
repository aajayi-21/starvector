"""The day timer across many days (spec BR1 section 3, spec PL1
section 3).

The timer starts the rollover each hour on the hour. These tests do
that with a clock that the test moves: the server of the test is the
app itself, and each firing is the rollover loop of the command. They prove what
the single-step tests do not: one new day for each calendar day, at
the rollover hour, for a week of firings, and the recovery after a
box that was down.
"""

import dataclasses
import datetime
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import (FIXED_CLOCK, QuickDigester, build_service_fixture,
                         mixed_wire_record)

from service import rollover, schedule, store
from service.server import create_app

TOKEN = "test-operator-token"


def _at(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text).replace(
        tzinfo=datetime.UTC)


class _Clock:
    """The instant of the simulated box. Each reader of the time in
    the server and in the day commands reads this one."""

    def __init__(self, text: str) -> None:
        self.instant = _at(text)

    def __call__(self) -> datetime.datetime:
        return self.instant

    def text(self) -> str:
        return self.instant.isoformat()


def _world(tmp_path, monkeypatch, *, hour: str, start: str,
           dev_only: bool = True, signup: str = "closed"):
    from service import day as day_module
    from service import server as server_module
    from validation import harness

    fixture = build_service_fixture(tmp_path, dev_only=dev_only)
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc=hour, signup=signup)
    clock = _Clock(start)
    monkeypatch.setattr(day_module, "utc_now", clock)
    monkeypatch.setattr(server_module, "utc_now", clock)
    # The stored timestamps of a day come from this clock too.
    monkeypatch.setattr(harness, "default_clock", clock.text)
    app = create_app(config, operator_token=TOKEN,
                     digester=QuickDigester(), usual_passwords=frozenset())
    client = TestClient(app, base_url="https://testserver")

    def post(path: str, _timeout: float) -> rollover.Answer:
        answer = client.post(path,
                             headers={"Authorization": f"Bearer {TOKEN}"})
        return rollover.Answer(status=answer.status_code, body=answer.json())

    return fixture, config, clock, post


def _fire(fixture, config, clock, post) -> store.RolloverRun:
    """One firing of the timer at the clock's instant."""
    return rollover.run_and_record(
        root=fixture["store"], closes_at_utc=config.closes_at_utc,
        post=post, now=clock, source="timer", sleep=lambda _: None,
        say=lambda _line: None)


def _hours(clock: _Clock, count: int):
    """Move the clock to each of the next hours on the hour."""
    for _ in range(count):
        clock.instant = schedule.next_firing_at(clock.instant)
        yield clock.instant


def _days(fixture) -> dict[str, store.DayRecord]:
    root = fixture["store"]
    return {day: store.read_day_record(root, day)
            for day in store.list_days(root)}


@pytest.mark.parametrize("hour", ["09:00", "22:00", "00:00"])
def test_one_day_opens_for_each_calendar_day_at_the_rollover_hour(
        tmp_path, monkeypatch, hour) -> None:
    fixture, config, clock, post = _world(
        tmp_path, monkeypatch, hour=hour, start="2026-12-01T06:30:00")
    moves: list[tuple[datetime.datetime, tuple[str, ...]]] = []
    for instant in _hours(clock, 7 * 24):
        run = _fire(fixture, config, clock, post)
        assert run.outcome in ("moved", "nothing due")
        if run.steps:
            moves.append((instant, run.steps))
        # A player gets an open day at each hour after the first firing.
        latest = store.latest_day(fixture["store"])
        assert store.read_day_record(fixture["store"], latest).status \
            == "open"
        assert latest == schedule.label_at(instant, hour)

    # The first firing opens the day of the calendar, and each move after it is
    # one close, one reveal, and one open at the rollover hour.
    assert moves[0][1] == ("open",)
    rollover_minutes = schedule.rollover_minutes(hour)
    for instant, steps in moves[1:]:
        assert steps == ("close", "reveal", "open")
        assert instant.hour * 60 + instant.minute == rollover_minutes
    assert len(moves) == 1 + 7

    days = _days(fixture)
    labels = sorted(days)
    assert len(labels) == 8
    # The labels are calendar days in sequence, with none left out.
    first = datetime.date.fromisoformat(labels[0])
    assert labels == [(first + datetime.timedelta(days=n)).isoformat()
                      for n in range(8)]
    for label in labels[:-1]:
        record = days[label]
        assert record.status == "revealed"
        closes = schedule.closes_at_for(label, hour)
        assert _at(record.closed_at[:19]) == closes
        assert _at(record.revealed_at[:19]) == closes
    assert days[labels[-1]].status == "open"
    # The day after one closes opens at that same hour: 24 hours each.
    for earlier, later in zip(labels[1:-1], labels[2:]):
        assert _at(days[later].opened_at[:19]) \
            == _at(days[earlier].opened_at[:19]) \
            + datetime.timedelta(days=1)


def test_a_firing_with_nothing_due_writes_no_record(tmp_path,
                                                    monkeypatch) -> None:
    fixture, config, clock, post = _world(
        tmp_path, monkeypatch, hour="09:00", start="2026-12-01T06:30:00")
    for _instant in _hours(clock, 30):
        _fire(fixture, config, clock, post)
    runs = store.list_rollover_runs(fixture["store"], 100)
    # 30 firings: the first open, and one rollover at 09:00 on each of
    # the two days in the window.
    assert [run.outcome for run in runs] == ["moved"] * 3
    assert sorted(run.steps for run in runs) == [
        ("close", "reveal", "open"), ("close", "reveal", "open"), ("open",)]


def test_a_box_that_was_down_opens_the_day_of_the_calendar(
        tmp_path, monkeypatch) -> None:
    fixture, config, clock, post = _world(
        tmp_path, monkeypatch, hour="09:00", start="2026-12-01T06:30:00")
    # With the hour at 09:00, the day with the label D runs from D at
    # 09:00. The firings of 07:00 to 11:00 thus open the day of the
    # date before, close it at 09:00, and open the day 2026-12-01.
    for _instant in _hours(clock, 5):
        _fire(fixture, config, clock, post)
    assert sorted(_days(fixture)) == ["2026-11-30", "2026-12-01"]
    # No firing for three days: the box was down.
    clock.instant = _at("2026-12-04T15:20:00")
    run = _fire(fixture, config, clock, post)
    assert run.steps == ("close", "reveal", "open")
    days = _days(fixture)
    # The day in play at the stop is closed and revealed. The new day
    # has the label of the calendar, and no day is opened for the days
    # with no play.
    assert sorted(days) == ["2026-11-30", "2026-12-01", "2026-12-04"]
    assert days["2026-12-01"].status == "revealed"
    assert days["2026-12-04"].status == "open"
    # From there the timer goes on, one day for each day.
    for _instant in _hours(clock, 48):
        _fire(fixture, config, clock, post)
    assert sorted(_days(fixture)) == ["2026-11-30", "2026-12-01",
                                      "2026-12-04", "2026-12-05",
                                      "2026-12-06"]


def test_the_week_scores_the_days_with_a_send(tmp_path, monkeypatch) -> None:
    fixture, config, clock, post = _world(
        tmp_path, monkeypatch, hour="09:00", start="2026-12-01T06:30:00")
    root = fixture["store"]
    for instant in _hours(clock, 3 * 24):
        _fire(fixture, config, clock, post)
        # One send in each open day, some hours after it opens.
        latest = store.latest_day(root)
        if instant.hour == 14 \
                and not store.submission_path(root, latest, "ade").is_file():
            store.write_once_json(
                store.submission_path(root, latest, "ade"),
                {"day": latest, "player": "ade", "trial_id": "f" * 32,
                 "received_at": clock.text(),
                 "record": mixed_wire_record()})
    days = _days(fixture)
    labels = sorted(days)
    assert labels == ["2026-11-30", "2026-12-01", "2026-12-02",
                      "2026-12-03"]
    assert [days[label].status for label in labels] \
        == ["revealed", "revealed", "revealed", "open"]
    # A day with no send closes and reveals too: the first day was
    # open for two hours, and nobody sent.
    assert store.list_submissions(root, "2026-11-30") == ()
    for label in ("2026-12-01", "2026-12-02"):
        row = json.loads(store.trial_row_path(root, label, "ade").read_text())
        assert 0.0 <= row["p"] <= 1.0
    # The send of the open day waits for its close.
    assert store.list_submissions(root, "2026-12-03") == ("ade",)
    assert not store.trial_row_path(root, "2026-12-03", "ade").is_file()


def test_the_timer_works_with_open_signup_and_no_player(
        tmp_path, monkeypatch) -> None:
    fixture, config, clock, post = _world(
        tmp_path, monkeypatch, hour="09:00", start="2026-12-01T06:30:00",
        dev_only=False, signup="open")
    # No player record is stored, and the first firing opens the first
    # day: a new deployment needs no hand to start its calendar.
    assert not store.any_player(fixture["store"])
    for _instant in _hours(clock, 30):
        run = _fire(fixture, config, clock, post)
        assert run.outcome in ("moved", "nothing due")
    days = _days(fixture)
    assert sorted(days) == ["2026-11-30", "2026-12-01", "2026-12-02"]
    assert [days[label].status for label in sorted(days)] \
        == ["revealed", "revealed", "open"]


def test_a_firing_with_no_operator_token_fails_and_says_why(
        tmp_path, monkeypatch) -> None:
    fixture, config, clock, _post = _world(
        tmp_path, monkeypatch, hour="09:00", start="2026-12-01T06:30:00",
        dev_only=False, signup="open")
    app = create_app(config, operator_token=TOKEN, digester=QuickDigester(),
                     usual_passwords=frozenset())
    client = TestClient(app, base_url="https://testserver")

    def bare(path: str, _timeout: float) -> rollover.Answer:
        answer = client.post(path)
        return rollover.Answer(status=answer.status_code, body=answer.json())

    clock.instant = _at("2026-12-01T07:00:00")
    run = _fire(fixture, config, clock, bare)
    assert run.outcome == "failed"
    assert "STARVECTOR_OPERATOR_TOKEN" in run.detail
    assert store.list_days(fixture["store"]) == ()


def test_a_close_that_fails_holds_the_next_day_until_it_heals(
        tmp_path, monkeypatch) -> None:
    """The limit of the automatic cycle (spec PL1 section 3): one day
    is active at a time, thus the next day opens after the close of the
    day before it. A close that fails is tried again at each firing,
    and no day is open in that time."""
    from service import day as day_module

    fixture, config, clock, post = _world(
        tmp_path, monkeypatch, hour="09:00", start="2026-12-01T09:30:00")
    root = fixture["store"]
    clock.instant = _at("2026-12-01T10:00:00")
    assert _fire(fixture, config, clock, post).steps == ("open",)
    assert store.latest_day(root) == "2026-12-01"

    true_close = day_module.close_day

    def failing_close(*_args, **_kwargs):
        raise RuntimeError("the provider does not answer")

    monkeypatch.setattr(day_module, "close_day", failing_close)
    # The rollover hour and the three firings after it: each one fails.
    clock.instant = _at("2026-12-02T08:00:00")
    for _instant in _hours(clock, 4):
        run = rollover.run_and_record(
            root=root, closes_at_utc=config.closes_at_utc, post=post,
            now=clock, source="timer", sleep=lambda _: None,
            say=lambda _line: None, retries=1)
        assert run.outcome == "failed"
        assert "the provider does not answer" in run.detail
    # No new day opened, and the day of before is not open for a send.
    assert store.list_days(root) == ("2026-12-01",)

    monkeypatch.setattr(day_module, "close_day", true_close)
    clock.instant = _at("2026-12-02T13:00:00")
    run = _fire(fixture, config, clock, post)
    assert run.steps == ("close", "reveal", "open")
    days = _days(fixture)
    assert sorted(days) == ["2026-12-01", "2026-12-02"]
    assert days["2026-12-02"].status == "open"
    # The day that opened late closes at its own hour: it is shorter,
    # and the calendar is on its hour again from there.
    clock.instant = _at("2026-12-03T09:00:00")
    assert _fire(fixture, config, clock, post).steps \
        == ("close", "reveal", "open")
    assert store.latest_day(root) == "2026-12-03"
