"""Invariant: rescore reproduces stored history byte-for-byte (S1 R8).

The pinned config compares and writes nothing. A different config
writes adjacent rows and touches nothing stored. A mismatch names
the day, the player, and the first differing field.
"""

import json
from pathlib import Path

import pytest

from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from service import store
from service.day import close_day, open_day, rescore_days, reveal_day

DAY = "2026-08-12"


def _played_world(tmp_path):
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": mixed_wire_record()})
    close_day(fixture["service_config"], providers=fixture["providers"],
              clock=lambda: FIXED_CLOCK)
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    return fixture


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


def test_rescore_with_the_pinned_config_is_byte_equal(tmp_path) -> None:
    fixture = _played_world(tmp_path)
    before = _snapshot(fixture["store"])
    counts = rescore_days(fixture["service_config"],
                          config_path=fixture["scoring_config_path"],
                          providers=fixture["providers"])
    assert counts["compared"] == 1
    assert counts["equal"] == 1
    assert counts["written"] == 0
    assert _snapshot(fixture["store"]) == before


def test_a_pinned_mismatch_names_the_field_and_writes_nothing(
        tmp_path) -> None:
    fixture = _played_world(tmp_path)
    row_path = store.trial_row_path(fixture["store"], DAY, "ade")
    row = json.loads(row_path.read_text())
    row["beaten"] = row["beaten"] + 1
    row_path.unlink()
    store.write_once_json(row_path, row)
    before = _snapshot(fixture["store"])
    with pytest.raises(store.StoreError,
                       match=r"day 2026-08-12, player ade.*beaten"):
        rescore_days(fixture["service_config"],
                     config_path=fixture["scoring_config_path"],
                     providers=fixture["providers"])
    assert _snapshot(fixture["store"]) == before


def test_a_different_config_writes_adjacent_rows_and_touches_nothing(
        tmp_path) -> None:
    fixture = _played_world(tmp_path)
    # A weights-only change: not in the commonness key (D12), thus
    # the rescore reads the prebuilt tables warm.
    document = json.loads(Path(fixture["scoring_config_path"]).read_text())
    document["fusion"]["weights"] = {"outline": 2.0, "element": 1.0}
    moved_path = Path(fixture["scoring_config_path"]).parent \
        / "scoring-config-reweighted.json"
    moved_path.write_text(json.dumps(document, indent=2) + "\n",
                          encoding="utf-8")

    before = _snapshot(fixture["store"])
    counts = rescore_days(fixture["service_config"],
                          config_path=str(moved_path),
                          providers=fixture["providers"])
    assert counts["written"] == 1
    assert counts["compared"] == 0
    after = _snapshot(fixture["store"])
    new_files = sorted(set(after) - set(before))
    assert len(new_files) == 1
    assert new_files[0].startswith("days/2026-08-12/trials/ade.")
    assert new_files[0].endswith(".json")
    for name in before:
        assert after[name] == before[name]
    adjacent = json.loads((fixture["store"] / new_files[0]).read_text())
    stored = json.loads(
        store.trial_row_path(fixture["store"], DAY, "ade").read_text())
    assert adjacent["scoring_config_hash"] != stored["scoring_config_hash"]
    assert adjacent["trial_id"] == stored["trial_id"]

    # Repeatable: the second run compares the adjacent row and adds
    # nothing.
    again = rescore_days(fixture["service_config"],
                         config_path=str(moved_path),
                         providers=fixture["providers"])
    assert again["written"] == 0
    assert _snapshot(fixture["store"]) == after


def test_an_open_day_is_skipped_with_a_count(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    counts = rescore_days(fixture["service_config"],
                          config_path=fixture["scoring_config_path"],
                          providers=fixture["providers"])
    assert counts["skipped_open"] == 1
    assert counts["days"] == 0


def test_a_colored_day_in_an_rgb_world_rescores_byte_equal(
        tmp_path) -> None:
    # The spec C1 rescore invariant: the promotion render is a pure
    # function of the stored record, thus a day with color strokes
    # reproduces byte-for-byte with the pinned config.
    from svc_fixture import colored_wire_record

    fixture = build_service_fixture(
        tmp_path, prep_overrides={"linedraw.stroke_color": "rgb"})
    open_day(fixture["service_config"], date=DAY,
             clock=lambda: FIXED_CLOCK, pick_seed="a" * 32,
             secret="b" * 64)
    store.write_once_json(
        store.submission_path(fixture["store"], DAY, "ade"),
        {"day": DAY, "player": "ade", "trial_id": "f" * 32,
         "received_at": FIXED_CLOCK, "record": colored_wire_record()})
    close_day(fixture["service_config"], providers=fixture["providers"],
              clock=lambda: FIXED_CLOCK)
    reveal_day(fixture["service_config"], clock=lambda: FIXED_CLOCK)
    before = _snapshot(fixture["store"])
    counts = rescore_days(fixture["service_config"],
                          config_path=fixture["scoring_config_path"],
                          providers=fixture["providers"])
    assert counts["compared"] == 1
    assert counts["equal"] == 1
    assert counts["written"] == 0
    assert _snapshot(fixture["store"]) == before
