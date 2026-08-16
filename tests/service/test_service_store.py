"""Unit: the trial store rules (spec S1 section 5) and the config.

One-write refusal, atomicity, the guarded status move, the
permanence README, and the strict server-config walk.
"""

import json
from pathlib import Path

import pytest

from service.config import ServiceConfigError, parse_service_config
from service.store import (DayRecord, PlayerRecord, StoreError, any_player,
                           day_record_path, ensure_store, latest_day,
                           list_days, list_players, list_submissions,
                           player_record_path, read_day_record,
                           read_player_or_none, read_player_record,
                           replace_player_token, set_player_status,
                           submission_path, trial_row_path,
                           update_day_status, write_day_record,
                           write_once_json, write_player_record)


def _record(day: str = "2026-08-12", status: str = "open") -> DayRecord:
    return DayRecord(
        day=day, trial_code="R7K2QX", target_id="t" * 64,
        pick_seed="s" * 32, secret="x" * 64,
        commitment="c" * 64, scoring_config_path="configs/scoring/x.json",
        scoring_config_hash="h" * 64, preparation_version_id="p" * 64,
        status=status, opened_at="2026-08-12T00:00:00+00:00",
        closed_at=None, revealed_at=None)


def _player(player: str = "ade", display_name: str = "Ade",
            status: str = "active") -> PlayerRecord:
    return PlayerRecord(
        player=player, display_name=display_name, token_hash="a" * 64,
        created_at="2026-08-15T00:00:00+00:00", status=status)


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


def test_a_legacy_record_names_the_migrate_command(tmp_path: Path) -> None:
    write_day_record(tmp_path, _record())
    path = day_record_path(tmp_path, "2026-08-12")
    raw = json.loads(path.read_text())
    del raw["trial_code"]
    path.write_text(json.dumps(raw))
    with pytest.raises(StoreError, match="service.day migrate"):
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


def test_closes_at_utc_is_optional_and_strict() -> None:
    absent = parse_service_config(_config_value(), "test")
    assert absent.closes_at_utc is None
    given = parse_service_config(
        _config_value(closes_at_utc="22:00"), "test")
    assert given.closes_at_utc == "22:00"
    for bad in ("24:00", "9:00", "22:60", "2200", 2200, ""):
        with pytest.raises(ServiceConfigError, match="closes_at_utc"):
            parse_service_config(_config_value(closes_at_utc=bad), "test")


def test_closes_at_utc_refuses_a_trailing_newline() -> None:
    # The dollar sign also matches before a trailing newline, and the
    # value goes into a timestamp string.
    with pytest.raises(ServiceConfigError, match="closes_at_utc"):
        parse_service_config(_config_value(closes_at_utc="22:00\n"), "test")


def test_the_configured_player_refuses_a_trailing_newline() -> None:
    # The same hole as closes_at_utc, and this value names a store
    # directory and is the fallback identity of spec M1 ruling 7.
    with pytest.raises(ServiceConfigError, match="file name"):
        parse_service_config(_config_value(player="ade\n"), "test")


def test_a_trial_code_with_a_trailing_newline_raises(tmp_path: Path) -> None:
    # re.match stops at the newline the dollar sign accepts, thus the
    # rule needs fullmatch or a tampered record passes.
    write_day_record(tmp_path, _record())
    path = day_record_path(tmp_path, "2026-08-12")
    raw = json.loads(path.read_text())
    raw["trial_code"] = "R7K2QX\n"
    path.write_text(json.dumps(raw))
    with pytest.raises(StoreError, match="trial_code"):
        read_day_record(tmp_path, "2026-08-12")


def test_a_day_directory_with_a_trailing_newline_is_not_a_day(
        tmp_path: Path) -> None:
    write_day_record(tmp_path, _record("2026-08-10"))
    (tmp_path / "days" / "2026-08-11\n").mkdir()
    assert list_days(tmp_path) == ("2026-08-10",)


def test_the_player_record_round_trips(tmp_path: Path) -> None:
    write_player_record(tmp_path, _player())
    assert read_player_record(tmp_path, "ade") == _player()


def test_the_player_field_set_is_strict(tmp_path: Path) -> None:
    write_player_record(tmp_path, _player())
    path = player_record_path(tmp_path, "ade")
    raw = json.loads(path.read_text())
    raw["extra"] = True
    path.write_text(json.dumps(raw))
    with pytest.raises(StoreError, match="fields"):
        read_player_record(tmp_path, "ade")
    del raw["extra"]
    del raw["status"]
    path.write_text(json.dumps(raw))
    with pytest.raises(StoreError, match="fields"):
        read_player_record(tmp_path, "ade")


def test_a_new_player_record_must_be_active(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="'active'"):
        write_player_record(tmp_path, _player(status="revoked"))


def test_the_player_mint_is_write_once(tmp_path: Path) -> None:
    write_player_record(tmp_path, _player())
    with pytest.raises(StoreError, match="one-write"):
        write_player_record(tmp_path, _player(display_name="Someone Else"))
    assert read_player_record(tmp_path, "ade").display_name == "Ade"


def test_a_name_that_is_not_a_legal_store_key_refuses(
        tmp_path: Path) -> None:
    # The dot name is the one that matters: it is what makes the
    # invite token's single separator unambiguous (spec M1 section 4).
    for name in ("A Player", "../escape", "ade.x", "", "a" * 65, "ade\n"):
        with pytest.raises(StoreError, match="player"):
            write_player_record(tmp_path, _player(player=name))


def test_the_display_name_rules(tmp_path: Path) -> None:
    for label in ("", "a" * 33, "bad\tlabel", "bad\nlabel",
                  "no break", "zero​width", "flip‮side",
                  " ade", "ade "):
        with pytest.raises(StoreError, match="display_name"):
            write_player_record(tmp_path, _player(display_name=label))
    for label in ("a" * 32, "Ada Lovelace", "安" * 32, "Ade \U0001f680"):
        store = tmp_path / label.encode("utf-8").hex()
        write_player_record(store, _player(display_name=label))
        assert read_player_record(store, "ade").display_name == label


def test_the_token_hash_shape_is_pinned(tmp_path: Path) -> None:
    for digest in ("A" * 64, "a" * 63, "g" * 64, "a" * 64 + "\n"):
        with pytest.raises(StoreError, match="token_hash"):
            write_player_record(
                tmp_path,
                PlayerRecord(player="ade", display_name="Ade",
                             token_hash=digest,
                             created_at="2026-08-15T00:00:00+00:00",
                             status="active"))


def test_a_record_whose_name_disagrees_with_its_file_refuses(
        tmp_path: Path) -> None:
    write_player_record(tmp_path, _player())
    path = player_record_path(tmp_path, "ade")
    raw = json.loads(path.read_text())
    raw["player"] = "someone-else"
    path.write_text(json.dumps(raw))
    with pytest.raises(StoreError, match="the file names"):
        read_player_record(tmp_path, "ade")


def test_the_token_replace_is_guarded(tmp_path: Path) -> None:
    write_player_record(tmp_path, _player())
    with pytest.raises(StoreError, match="needs 'revoked'"):
        replace_player_token(tmp_path, "ade", expect_status="revoked",
                             new_token_hash="b" * 64)
    moved = replace_player_token(tmp_path, "ade", expect_status="active",
                                 new_token_hash="b" * 64)
    assert moved.token_hash == "b" * 64
    assert moved.player == "ade"
    assert moved.created_at == _player().created_at
    assert read_player_record(tmp_path, "ade").token_hash == "b" * 64


def test_the_player_status_move_is_guarded(tmp_path: Path) -> None:
    write_player_record(tmp_path, _player())
    moved = set_player_status(tmp_path, "ade", expect_status="active",
                              new_status="revoked")
    assert moved.status == "revoked"
    with pytest.raises(StoreError, match="needs 'active'"):
        set_player_status(tmp_path, "ade", expect_status="active",
                          new_status="revoked")
    back = set_player_status(tmp_path, "ade", expect_status="revoked",
                             new_status="active")
    assert back.status == "active"


def test_the_player_listing_skips_foreign_files(tmp_path: Path) -> None:
    assert list_players(tmp_path) == ()
    write_player_record(tmp_path, _player("bru", "Bru"))
    write_player_record(tmp_path, _player("ade", "Ade"))
    (player_record_path(tmp_path, "ade").parent / "note.txt").write_text("x")
    assert list_players(tmp_path) == ("ade", "bru")


def test_any_player_is_the_access_switch(tmp_path: Path) -> None:
    assert any_player(tmp_path) is False
    (tmp_path / "players").mkdir(parents=True)
    assert any_player(tmp_path) is False
    write_player_record(tmp_path, _player())
    assert any_player(tmp_path) is True
    set_player_status(tmp_path, "ade", expect_status="active",
                      new_status="revoked")
    assert any_player(tmp_path) is True


def test_the_request_path_reader_answers_none_for_an_unknown_name(
        tmp_path: Path) -> None:
    assert read_player_or_none(tmp_path, "ade") is None
    assert read_player_or_none(tmp_path, "../escape") is None
    write_player_record(tmp_path, _player())
    found = read_player_or_none(tmp_path, "ade")
    assert found is not None and found.player == "ade"
