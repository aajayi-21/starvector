"""Integration: the V2 harness — invariant 6, the baseline shape.

Runs on a hand-built 200-image prepared pool so the trial-score lattice
(D + 1 values) stays far below the KS acceptance line.
"""

import json

import pytest

from conftest import (FIXED_CLOCK, build_direct_prepared_pool,
                      make_scoring_config, scoring_fakes)
from validation.v2 import run_v2

POOL_SIZE = 200
TRIALS = 24

# The 1% acceptance line at 24 trials: 1.628 / sqrt(24).
ACCEPTANCE = 0.333


def _run(tmp_path, seed: int = 7):
    prepared = build_direct_prepared_pool(tmp_path, POOL_SIZE)
    config = make_scoring_config(
        prepared["prep_record_path"],
        **{"commonness.dataset.fake_pair_count": 128,
           "commonness.background_count": 12,
           "validation.v2_trial_count": TRIALS,
           "validation.v2_target_seed": seed})
    report = run_v2(
        config,
        data_root=prepared["data"],
        records_root=tmp_path / "records",
        providers=scoring_fakes(pair_count=128),
        clock=lambda: FIXED_CLOCK,
        code_version="test",
    )
    return prepared, report


def test_no_information_trials_sit_below_the_acceptance_line(
        tmp_path) -> None:
    _, report = _run(tmp_path)
    assert report.trial_count == TRIALS
    assert report.statistic < ACCEPTANCE
    assert report.significance > 0.01
    assert report.decoy_count_min == POOL_SIZE - 1
    assert report.decoy_count_max == POOL_SIZE - 1


def test_the_record_carries_the_statistic_and_verdict_fields(
        tmp_path) -> None:
    _, report = _run(tmp_path)
    assert report.record_path is not None
    record = json.loads(open(report.record_path, encoding="utf-8").read())
    assert record["harness"] == "v2"
    assert record["trial_count"] == TRIALS
    assert record["ks_statistic"] == pytest.approx(report.statistic,
                                                   abs=1e-6)
    assert record["verdict"] == "pending"
    assert record["dev_only"] is True


def test_the_seeded_targets_are_pinned_by_the_seed(tmp_path) -> None:
    _, first = _run(tmp_path / "a", seed=7)
    _, again = _run(tmp_path / "b", seed=7)
    assert first.trials == again.trials
    _, different = _run(tmp_path / "c", seed=8)
    assert different.trials != first.trials
