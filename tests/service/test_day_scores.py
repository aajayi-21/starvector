"""The day-score cache and the day rank of spec AG1 section 5."""

import json
from pathlib import Path

import numpy as np
import pytest
from svc_fixture import FIXED_CLOCK, build_service_fixture, mixed_wire_record

from core.aggregate import corrected_score
from core.ranking import decoy_set, rank
from pipeline.config import load_scoring_config
from service import day_scores, scoring, store
from service.day import build_day_scores, close_day, open_day

DAY = "2026-08-12"


def _closed_world(tmp_path, players=("ade", "bru", "cy")):
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    for position, player in enumerate(players):
        record = {**mixed_wire_record(),
                  "impressions": [f"impression {position}", "a far ridge"]}
        store.write_once_json(
            store.submission_path(fixture["store"], DAY, player),
            {"day": DAY, "player": player, "trial_id": f"{position}" * 32,
             "received_at": FIXED_CLOCK, "record": record})
    close_day(config, clock=lambda: FIXED_CLOCK)
    return fixture


def test_the_close_writes_the_rows_and_the_day_rank(tmp_path) -> None:
    fixture = _closed_world(tmp_path)
    data_root = Path(fixture["service_config"].data_root)
    record = store.read_day_record(fixture["store"], DAY)
    index = json.loads(day_scores.index_path(
        data_root, DAY, record.scoring_config_hash).read_text())
    assert index["players"] == ["ade", "bru", "cy"]
    assert index["pool_count"] == len(fixture["image_ids"])
    assert 0.0 < index["day_rank"] < 1.0
    scores = np.load(day_scores.scores_path(
        data_root, DAY, record.scoring_config_hash))
    assert scores.shape == (3, len(fixture["image_ids"]))
    assert scores.dtype == np.float32


def test_the_cached_rows_give_the_stored_trial_rows(tmp_path) -> None:
    """One number: the cache row ranks to the trial row that the close
    stored, thus the day rank reads the scores that gave the players
    their trial scores."""
    fixture = _closed_world(tmp_path)
    data_root = Path(fixture["service_config"].data_root)
    record = store.read_day_record(fixture["store"], DAY)
    config = load_scoring_config(Path(record.scoring_config_path))
    wired = scoring.wire_for_open(config, record.scoring_config_path,
                                  data_root)
    scores = np.load(day_scores.scores_path(
        data_root, DAY, record.scoring_config_hash))
    decoys = decoy_set(wired.context.index, record.target_id)
    for row, player in zip(scores, ["ade", "bru", "cy"]):
        stored = store.read_json_or_none(
            store.trial_row_path(fixture["store"], DAY, player))
        trial = rank(row, record.target_id, decoys, wired.context.index)
        assert (trial.beaten, trial.tied, trial.decoy_count) == (
            stored["beaten"], stored["tied"], stored["decoy_count"])
        assert corrected_score(trial.beaten, trial.tied,
                               trial.decoy_count) > 0.0


def test_a_day_with_no_send_writes_no_file(tmp_path) -> None:
    fixture = _closed_world(tmp_path, players=())
    data_root = Path(fixture["service_config"].data_root)
    record = store.read_day_record(fixture["store"], DAY)
    assert not day_scores.has_day_scores(data_root, DAY,
                                         record.scoring_config_hash)
    with pytest.raises(day_scores.DayScoresError, match="day-scores"):
        day_scores.read_day_rank(data_root, DAY, record.scoring_config_hash)


def test_the_command_makes_a_removed_file_again_with_equal_bytes(
        tmp_path, capsys) -> None:
    fixture = _closed_world(tmp_path)
    config = fixture["service_config"]
    data_root = Path(config.data_root)
    record = store.read_day_record(fixture["store"], DAY)
    paths = (day_scores.scores_path(data_root, DAY,
                                    record.scoring_config_hash),
             day_scores.index_path(data_root, DAY,
                                   record.scoring_config_hash))
    before = [path.read_bytes() for path in paths]
    assert build_day_scores(config)["present"] == 1
    for path in paths:
        path.unlink()
    counts = build_day_scores(config, providers=fixture["providers"])
    assert counts == {"days": 1, "written": 1, "present": 0}
    assert [path.read_bytes() for path in paths] == before


def test_the_command_refuses_an_open_day(tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    config = fixture["service_config"]
    open_day(config, date=DAY, clock=lambda: FIXED_CLOCK,
             pick_seed="a" * 32, secret="b" * 64)
    with pytest.raises(store.StoreError, match="closed or revealed"):
        build_day_scores(config, date=DAY)


def test_a_bad_day_rank_is_not_written(tmp_path) -> None:
    with pytest.raises(day_scores.DayScoresError, match=r"\(0, 1\)"):
        day_scores.write_day_scores(
            tmp_path, DAY, "h" * 64, players=["ade"],
            scores=np.zeros((1, 4), dtype=np.float32), rank=1.0)
    with pytest.raises(day_scores.DayScoresError, match="sorted"):
        day_scores.write_day_scores(
            tmp_path, DAY, "h" * 64, players=["bru", "ade"],
            scores=np.zeros((2, 4), dtype=np.float32), rank=0.5)
