"""Unit tests for the fit objective's 0.5 rule (ruling 2026-08-10).

A trial with no channel the candidate reads counts 0.5, the trial
set stays fixed across grid points, and the basis is a property of
the grid — the review found the former key-driven rules crashed the
simplex and mixed two data bases in one V4 cost.
"""

import numpy as np
import pytest

from validation.fit import (LabeledTrial, mean_trial_score, readable_trial)


def _trial(key: str, channels: tuple[str, ...],
           target_wins: bool) -> LabeledTrial:
    # Three images, and the target is image a. A winning trial
    # ranks the target on top, a losing one on the bottom.
    top = 1.0 if target_wins else -1.0
    scores = {name: np.asarray([top, 0.0, -top], dtype=np.float32)
              for name in channels}
    return LabeledTrial(key=key, standardized=scores, label="a" * 64)


def _index():
    from tests.conftest import make_pool_index

    dimension = 4
    ids = ("a" * 64, "b" * 64, "c" * 64)
    return make_pool_index(
        index_id="f" * 64, image_ids=ids,
        outline_vectors=np.zeros((3, 6, dimension), dtype=np.float32),
        outline_space_mean=np.zeros(dimension, dtype=np.float32),
        group_ids=ids,
        pool_image_count=3, vocabulary=("x",), pool_frequency=(1,),
        vocabulary_vectors=np.ones((1, dimension), dtype=np.float32),
        incidence=np.zeros((3, 1), dtype=np.int32),
        element_space_mean=np.zeros(dimension, dtype=np.float32))


def test_a_zero_weight_channel_does_not_read_a_trial() -> None:
    trial = _trial("t1", ("element",), True)
    assert readable_trial(trial, {"element": 1.0}) is True
    assert readable_trial(trial, {"element": 0.0, "outline": 1.0}) is False
    assert readable_trial(trial, {"placement": 1.0}) is False


def test_an_unreadable_trial_counts_chance() -> None:
    index = _index()
    trials = [_trial("t1", ("element",), True),
              _trial("t2", ("placement",), True)]
    # The element-only candidate reads t1 (p = 1.0 with two decoys
    # below it) and counts 0.5 for t2: mean 0.75.
    value = mean_trial_score(trials, {"element": 1.0}, index)
    assert value == pytest.approx(0.75)


def test_a_fully_unreadable_split_sits_at_chance() -> None:
    index = _index()
    trials = [_trial("t1", ("element",), True),
              _trial("t2", ("element",), False)]
    value = mean_trial_score(trials, {"placement": 1.0}, index)
    assert value == pytest.approx(0.5)
