"""Integration: the daily rollover command (spec BR1 section 3).

The command moves the server app itself through its operator
endpoints, with the calendar pinned. It closes a day only when the
day is due, continues after a stop, opens one day at most, and holds
a lock.
"""

import dataclasses
import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import rollover, store
from service.day import open_day
from service.server import create_app

HOUR = "22:00"


def _at(text: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(text).replace(tzinfo=datetime.UTC)


class _Clock:
    """A settable instant, shared by the command and the server."""

    def __init__(self, text: str) -> None:
        self.instant = _at(text)

    def __call__(self) -> datetime.datetime:
        return self.instant


def _world(tmp_path, monkeypatch, instant: str):
    from service import day as day_module

    fixture = build_service_fixture(tmp_path)
    config = dataclasses.replace(fixture["service_config"],
                                 closes_at_utc=HOUR)
    clock = _Clock(instant)
    monkeypatch.setattr(day_module, "utc_now", clock)
    client = TestClient(create_app(config))

    def post(path: str, _timeout: float) -> rollover.Answer:
        answer = client.post(path)
        return rollover.Answer(status=answer.status_code, body=answer.json())

    return fixture, config, client, clock, post


def _run(fixture, clock, post, **keywords):
    said: list[str] = []
    steps = rollover.run_rollover(root=fixture["store"], closes_at_utc=HOUR,
                                  post=post, now=clock, sleep=lambda _: None,
                                  say=said.append, **keywords)
    return steps, said


def test_an_empty_store_opens_the_running_day(tmp_path, monkeypatch) -> None:
    fixture, _config, _client, clock, post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")
    steps, _said = _run(fixture, clock, post)
    assert steps == ["open"]
    assert store.list_days(fixture["store"]) == ("2026-09-24",)


def test_a_day_that_is_not_due_is_left_alone(tmp_path, monkeypatch) -> None:
    fixture, _config, _client, clock, post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")
    _run(fixture, clock, post)
    before = store.read_day_record(fixture["store"], "2026-09-24")
    clock.instant = _at("2026-09-24T21:59:00")
    steps, said = _run(fixture, clock, post)
    assert steps == []
    assert "not due" in said[-1]
    assert store.read_day_record(fixture["store"], "2026-09-24") == before


def test_a_due_day_closes_reveals_and_the_next_opens(tmp_path,
                                                     monkeypatch) -> None:
    fixture, _config, client, clock, post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")
    _run(fixture, clock, post)
    assert client.post("/api/submission",
                       json=mixed_wire_record()).status_code == 200
    clock.instant = _at("2026-09-24T22:00:03")
    steps, _said = _run(fixture, clock, post)
    assert steps == ["close", "reveal", "open"]
    root = fixture["store"]
    assert store.read_day_record(root, "2026-09-24").status == "revealed"
    assert store.trial_row_path(root, "2026-09-24", "ade").is_file()
    new_day = store.read_day_record(root, "2026-09-25")
    assert new_day.status == "open"
    # The countdown and the timer agree on the next close.
    assert client.get("/api/day").json()["closes_at"] \
        == "2026-09-25T22:00:00+00:00"
    # A second start in the same minute finds nothing to do.
    steps, _said = _run(fixture, clock, post)
    assert steps == []


def test_a_rollover_continues_after_a_stop(tmp_path, monkeypatch) -> None:
    fixture, _config, _client, clock, post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")
    _run(fixture, clock, post)
    root = fixture["store"]
    # A stop after the close: the day is closed and not revealed.
    store.update_day_status(root, "2026-09-24", expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)
    clock.instant = _at("2026-09-24T22:05:00")
    steps, _said = _run(fixture, clock, post)
    assert steps == ["close", "reveal", "open"]
    assert store.read_day_record(root, "2026-09-24").status == "revealed"


def test_a_closed_day_left_behind_is_revealed_first(tmp_path,
                                                    monkeypatch) -> None:
    fixture, config, _client, clock, post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")
    open_day(config, date="2026-09-24", clock=lambda: FIXED_CLOCK)
    root = fixture["store"]
    store.update_day_status(root, "2026-09-24", expect_status="open",
                            new_status="closing", timestamp_field=None,
                            timestamp=None)
    store.update_day_status(root, "2026-09-24", expect_status="closing",
                            new_status="closed", timestamp_field="closed_at",
                            timestamp=FIXED_CLOCK)
    steps, _said = _run(fixture, clock, post)
    assert steps == ["reveal", "open"]
    assert store.list_days(root) == ("2026-09-24", "2026-09-25")


def test_a_failing_close_retries_then_stops(tmp_path, monkeypatch) -> None:
    fixture, _config, _client, clock, _post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")
    calls: list[str] = []

    def failing(path: str, _timeout: float) -> rollover.Answer:
        calls.append(path)
        return rollover.Answer(status=400, body={"cause": "close-failed",
                                                 "detail": "provider 503"})

    open_day(dataclasses.replace(fixture["service_config"],
                                 closes_at_utc=HOUR),
             clock=lambda: FIXED_CLOCK)
    clock.instant = _at("2026-09-24T22:00:00")
    with pytest.raises(rollover.RolloverError, match="provider 503"):
        _run(fixture, clock, failing, retries=2)
    assert calls == ["/api/day/close"] * 3


def test_no_answer_is_retried(tmp_path, monkeypatch) -> None:
    fixture, _config, _client, clock, post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")
    attempts = {"count": 0}

    def flaky(path: str, timeout: float) -> rollover.Answer:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise rollover.TransportError("connection refused")
        return post(path, timeout)

    steps, said = _run(fixture, clock, flaky)
    assert steps == ["open"]
    assert any("again in" in line for line in said)


def test_a_refused_token_stops_at_once(tmp_path, monkeypatch) -> None:
    fixture, _config, _client, clock, _post = _world(
        tmp_path, monkeypatch, "2026-09-24T10:00:00")

    def unauthorized(_path: str, _timeout: float) -> rollover.Answer:
        return rollover.Answer(status=401, body={"detail": "unauthorized"})

    with pytest.raises(rollover.RolloverError, match="operator token"):
        _run(fixture, clock, unauthorized)


def test_the_plan_names_each_status() -> None:
    instant = _at("2026-09-24T12:00:00")
    plan = rollover.plan_step
    assert plan(rollover.Latest(None, None), instant, HOUR) == "open"
    assert plan(rollover.Latest("2026-09-24", "open"), instant,
                HOUR) == "wait"
    assert plan(rollover.Latest("2026-09-23", "open"), instant,
                HOUR) == "close"
    assert plan(rollover.Latest("2026-09-24", "closing"), instant,
                HOUR) == "close"
    assert plan(rollover.Latest("2026-09-24", "closed"), instant,
                HOUR) == "reveal"
    assert plan(rollover.Latest("2026-09-24", "revealed"), instant,
                HOUR) == "open"


def test_the_lock_admits_one_rollover(tmp_path) -> None:
    lock = tmp_path / "run" / "lock"
    first = rollover.hold_lock(lock)
    assert first is not None
    try:
        assert rollover.hold_lock(lock) is None
    finally:
        import os

        os.close(first)
    second = rollover.hold_lock(lock)
    assert second is not None


def test_the_command_refuses_with_no_hour(tmp_path, capsys) -> None:
    import json

    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    path = Path(tmp_path) / "service.json"
    path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port}), encoding="utf-8")
    assert rollover.main(["--service-config", str(path),
                          "--lock", str(tmp_path / "lock")]) == 1
    assert "closes_at_utc" in capsys.readouterr().err


def _config_file(tmp_path, config) -> Path:
    import json

    path = Path(tmp_path) / "service.json"
    path.write_text(json.dumps({
        "config_version": 1, "player": config.player,
        "scoring_config": config.scoring_config,
        "data_root": config.data_root, "store_root": config.store_root,
        "port": config.port, "closes_at_utc": HOUR}), encoding="utf-8")
    return path


def test_the_planned_steps_assume_each_move() -> None:
    instant = _at("2026-09-24T22:30:00")
    steps = rollover.planned_steps
    assert steps(rollover.Latest(None, None), instant, HOUR) == ("open",)
    assert steps(rollover.Latest("2026-09-25", "open"), instant,
                 HOUR) == ()
    assert steps(rollover.Latest("2026-09-24", "open"), instant,
                 HOUR) == ("close", "reveal", "open")
    assert steps(rollover.Latest("2026-09-24", "closing"), instant,
                 HOUR) == ("close", "reveal", "open")
    assert steps(rollover.Latest("2026-09-24", "closed"), instant,
                 HOUR) == ("reveal", "open")
    assert steps(rollover.Latest("2026-09-24", "revealed"), instant,
                 HOUR) == ("open",)


def test_a_paused_rollover_moves_nothing_and_says_so(
        tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("STARVECTOR_HEALTHCHECK_URL", raising=False)
    fixture = build_service_fixture(tmp_path)
    path = _config_file(tmp_path, fixture["service_config"])
    store.write_rollover_control(fixture["store"], store.RolloverControl(
        paused=True, changed_at=FIXED_CLOCK, note="holiday"))
    # The base address answers nothing: a paused rollover posts nothing.
    assert rollover.main(["--service-config", str(path), "--base-url",
                          "http://127.0.0.1:9", "--source", "timer"]) == 0
    assert "nothing moves" in capsys.readouterr().out
    assert store.latest_day(fixture["store"]) is None
    (run,) = store.list_rollover_runs(fixture["store"], 5)
    assert run.outcome == "paused" and run.source == "timer"
    assert "holiday" in run.detail
    # The default lock is the store's, the one the console holds.
    assert store.rollover_lock_path(fixture["store"]).is_file()

    assert rollover.main(["--service-config", str(path), "--plan"]) == 0
    assert "paused" in capsys.readouterr().out


def test_a_failed_rollover_exits_one_with_its_record(
        tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("STARVECTOR_HEALTHCHECK_URL", raising=False)
    fixture = build_service_fixture(tmp_path)
    path = _config_file(tmp_path, fixture["service_config"])
    assert rollover.main(["--service-config", str(path), "--base-url",
                          "http://127.0.0.1:9", "--retries", "0"]) == 1
    assert "rollover failed" in capsys.readouterr().err
    (run,) = store.list_rollover_runs(fixture["store"], 5)
    assert run.outcome == "failed" and run.source == "command-line"
    assert run.steps == ()
    assert "no answer" in run.detail


def test_the_next_rollover_is_the_first_hour_at_or_after_now() -> None:
    from service import schedule

    at = schedule.next_rollover_at
    assert at(_at("2026-09-24T12:00:00"), HOUR) == _at("2026-09-24T22:00:00")
    assert at(_at("2026-09-24T22:00:00"), HOUR) == _at("2026-09-24T22:00:00")
    assert at(_at("2026-09-24T22:00:01"), HOUR) == _at("2026-09-25T22:00:00")
    assert at(_at("2026-09-24T23:30:00"), "00:00") \
        == _at("2026-09-25T00:00:00")


def test_the_run_records_read_back_newest_first(tmp_path) -> None:
    root = Path(tmp_path) / "store"
    for minute in ("01", "03", "02"):
        store.write_rollover_run(root, store.RolloverRun(
            started_at=f"2026-09-24T22:{minute}:00+00:00",
            finished_at=f"2026-09-24T22:{minute}:30+00:00",
            source="timer", outcome="nothing due", steps=(), detail=""))
    runs = store.list_rollover_runs(root, 2)
    assert [run.started_at[14:16] for run in runs] == ["03", "02"]
    with pytest.raises(store.StoreError):
        store.write_rollover_run(root, store.RolloverRun(
            started_at="2026-09-24T22:00:00+00:00",
            finished_at="2026-09-24T22:00:00+00:00", source="cron",
            outcome="moved", steps=(), detail=""))
