"""Integration: the V2c color gate (spec C1 section 6).

Offline with fakes on an rgb fixture world: the harness runs end to
end, writes its record, and refuses a mono world.
"""

import json

import pytest

from conftest import (FIXED_CLOCK, build_direct_prepared_pool,
                      make_scoring_config, scoring_fakes)
from validation.colorize import PALETTE, colorized_record
from validation.v2c import run_v2c

POOL_SIZE = 60
TRIALS = 12


def _run(tmp_path, overrides=None):
    prepared = build_direct_prepared_pool(tmp_path, POOL_SIZE,
                                          overrides=overrides)
    config = make_scoring_config(
        prepared["prep_record_path"],
        **{"commonness.dataset.fake_pair_count": 64,
           "commonness.background_count": 8,
           "validation.v2_trial_count": TRIALS,
           "validation.submission_mode": "sketch"})
    return run_v2c(
        config,
        data_root=prepared["data"],
        records_root=tmp_path / "records",
        providers=scoring_fakes(pair_count=64),
        clock=lambda: FIXED_CLOCK,
        code_version="test",
    )


def test_the_gate_runs_and_writes_its_record(tmp_path) -> None:
    report = _run(tmp_path, overrides={"linedraw.stroke_color": "rgb"})
    assert report.trial_count == TRIALS
    assert 0.0 <= report.mean_abs_delta_p <= 1.0
    assert report.max_abs_delta_p >= report.mean_abs_delta_p
    assert report.record_path is not None
    record = json.loads(open(report.record_path, encoding="utf-8").read())
    assert record["harness"] == "v2c"
    assert record["verdict"] == "pending"
    assert {"mono_ks_statistic", "color_ks_statistic", "mean_delta_p",
            "mean_abs_delta_p", "max_abs_delta_p"} <= set(record)


def test_the_gate_refuses_a_mono_world(tmp_path) -> None:
    with pytest.raises(ValueError, match="rgb"):
        _run(tmp_path)


def test_colorized_record_is_seeded_and_touches_colors_alone() -> None:
    record = {
        "impressions": ["water"],
        "canvas_strokes": [
            {"points": [[0.1, 0.1], [0.2, 0.2]], "group_id": None},
            {"points": [[0.3, 0.3], [0.4, 0.4]], "group_id": None},
        ],
        "groups": [], "relations": [], "pasted_text": None,
    }
    first = colorized_record(record, 7, "pair-1")
    again = colorized_record(record, 7, "pair-1")
    other = colorized_record(record, 8, "pair-1")
    assert first == again
    assert first != other
    assert "color" not in record["canvas_strokes"][0]
    for stroke, plain in zip(first["canvas_strokes"],
                             record["canvas_strokes"]):
        assert stroke["color"] in PALETTE
        assert stroke["points"] == plain["points"]
        assert stroke["group_id"] == plain["group_id"]
    stripped = [{k: v for k, v in stroke.items() if k != "color"}
                for stroke in first["canvas_strokes"]]
    assert stripped == record["canvas_strokes"]
