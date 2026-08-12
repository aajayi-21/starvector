"""Unit: the trial store rules (spec S1 section 5) and the config.

One-write refusal, atomicity, the guarded status move, the
permanence README, and the strict server-config walk.
"""

import json
from pathlib import Path

import pytest

from service.config import ServiceConfigError, parse_service_config
from service.store import (DayRecord, StoreError, day_record_path,
                           ensure_store, latest_day, list_days,
                           list_submissions, read_day_record,
                           submission_path, trial_row_path,
                           update_day_status, write_day_record,
                           write_once_json)


def _record(day: str = "2026-08-12", status: str = "open") -> DayRecord:
    return DayRecord(
        day=day, trial_code="R7K2QX", target_id="t" * 64,
        pick_seed="s" * 32, secret="x" * 64,
        commitment="c" * 64, scoring_config_path="configs/scoring/x.json",
        scoring_config_hash="h" * 64, preparation_version_id="p" * 64,
        status=status, opened_at="2026-08-12T00:00:00+00:00",
        closed_at=None, revealed_at=None)


def test_write_once_refuses_a_second_write(tmp_path: Path) -> None:
    path = tmp_path / "row.json"
    write_once_json(path, {"a": 1})
    with pytest.raises(StoreError, match="one-write"):
        write_once_json(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}


def test_write_once_leaves_no_temporary_sibling(tmp_path: Path) -> None:
    path = tmp_path / "row.json"
    write_once_json(path, {"a": 1})
    with pytest.raises(StoreError):
        write_once_json(path, {"a": 2})
    assert [entry.name for entry in tmp_path.iterdir()] == ["row.json"]


def test_the_day_record_round_trips(tmp_path: Path) -> None:
    write_day_record(tmp_path, _record())
    assert read_day_record(tmp_path, "2026-08-12") == _record()


def test_a_new_day_record_must_be_open(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="'open'"):
        write_day_record(tmp_path, _record(status="closed"))


def test_the_status_move_is_guarded(tmp_path: Path) -> None:
    write_day_record(tmp_path, _record())
    with pytest.raises(StoreError, match="needs 'closed'"):
        update_day_status(tmp_path, "2026-08-12", expect_status="closed",
                          new_status="revealed",
                          timestamp_field="revealed_at",
                          timestamp="2026-08-13T00:00:00+00:00")
    moved = update_day_status(tmp_path, "2026-08-12", expect_status="open",
                              new_status="closed",
                              timestamp_field="closed_at",
                              timestamp="2026-08-12T20:00:00+00:00")
    assert moved.status == "closed"
    assert read_day_record(tmp_path, "2026-08-12").closed_at \
        == "2026-08-12T20:00:00+00:00"


def test_a_tampered_day_record_raises(tmp_path: Path) -> None:
    write_day_record(tmp_path, _record())
    path = day_record_path(tmp_path, "2026-08-12")
    raw = json.loads(path.read_text())
    raw["extra"] = True
    path.write_text(json.dumps(raw))
    with pytest.raises(StoreError, match="fields"):
        read_day_record(tmp_path, "2026-08-12")


def test_a_malformed_trial_code_raises(tmp_path: Path) -> None:
    write_day_record(tmp_path, _record())
    path = day_record_path(tmp_path, "2026-08-12")
    raw = json.loads(path.read_text())
    raw["trial_code"] = "abc"
    path.write_text(json.dumps(raw))
    with pytest.raises(StoreError, match="trial_code"):
        read_day_record(tmp_path, "2026-08-12")


def test_ensure_store_writes_the_permanence_readme_once(
        tmp_path: Path) -> None:
    ensure_store(tmp_path)
    text = (tmp_path / "README.md").read_text()
    assert "permanent" in text
    (tmp_path / "README.md").write_text("edited")
    ensure_store(tmp_path)
    assert (tmp_path / "README.md").read_text() == "edited"


def test_day_listing_and_paths(tmp_path: Path) -> None:
    assert list_days(tmp_path) == ()
    assert latest_day(tmp_path) is None
    write_day_record(tmp_path, _record("2026-08-10"))
    write_day_record(tmp_path, _record("2026-08-12"))
    (tmp_path / "days" / "not-a-day").mkdir()
    assert list_days(tmp_path) == ("2026-08-10", "2026-08-12")
    assert latest_day(tmp_path) == "2026-08-12"
    assert submission_path(tmp_path, "2026-08-12", "ade").name == "ade.json"
    assert trial_row_path(tmp_path, "2026-08-12", "ade",
                          "abcd1234").name == "ade.abcd1234.json"


def test_submission_listing_skips_foreign_files(tmp_path: Path) -> None:
    write_once_json(submission_path(tmp_path, "2026-08-12", "ade"), {})
    root = submission_path(tmp_path, "2026-08-12", "ade").parent
    (root / "note.txt").write_text("x")
    assert list_submissions(tmp_path, "2026-08-12") == ("ade",)


def _config_value(**overrides: object) -> dict:
    value: dict = {
        "config_version": 1, "player": "ade",
        "scoring_config": "configs/scoring/dev-wit-mixed.json",
        "data_root": "data", "store_root": "store", "port": 8321,
    }
    value.update(overrides)
    return value


def test_the_service_config_parses_and_is_strict() -> None:
    config = parse_service_config(_config_value(), "test")
    assert config.player == "ade"
    assert config.port == 8321
    with pytest.raises(ServiceConfigError, match="unknown"):
        parse_service_config(_config_value(extra=1), "test")
    missing = _config_value()
    del missing["port"]
    with pytest.raises(ServiceConfigError, match="missing"):
        parse_service_config(missing, "test")


def test_the_player_name_shape_is_pinned() -> None:
    with pytest.raises(ServiceConfigError, match="file name"):
        parse_service_config(_config_value(player="A Player"), "test")
    with pytest.raises(ServiceConfigError, match="file name"):
        parse_service_config(_config_value(player="../escape"), "test")


def test_the_port_range_is_checked() -> None:
    with pytest.raises(ServiceConfigError, match="port"):
        parse_service_config(_config_value(port=0), "test")
    with pytest.raises(ServiceConfigError, match="port"):
        parse_service_config(_config_value(port=True), "test")
