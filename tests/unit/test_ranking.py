"""Unit tests for Layer 8: decoy set construction and the trial score."""

import numpy as np
import pytest

from core.ranking import decoy_set, rank
from core.types import PoolIndex, TrialScore
from tests.conftest import make_pool_index

_IDS = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)


def _index() -> PoolIndex:
    # a and b share one near-duplicate group. c and d are singletons.
    return make_pool_index(
        index_id="f" * 64,
        image_ids=_IDS,
        outline_vectors=np.zeros((4, 6, 2), dtype=np.float32),
        outline_space_mean=np.zeros(2, dtype=np.float32),
        group_ids=(_IDS[0], _IDS[0], _IDS[2], _IDS[3]),
    )


def test_the_decoy_set_removes_the_full_group() -> None:
    decoys = decoy_set(_index(), _IDS[0])
    assert decoys.tolist() == [False, False, True, True]
    decoys = decoy_set(_index(), _IDS[1])
    assert decoys.tolist() == [False, False, True, True]
    decoys = decoy_set(_index(), _IDS[2])
    assert decoys.tolist() == [True, True, False, True]


def test_the_trial_score_is_pinned() -> None:
    fused = np.asarray([0.9, 0.1, 0.5, 0.7], dtype=np.float32)
    decoys = decoy_set(_index(), _IDS[0])
    trial = rank(fused, _IDS[0], decoys, _index())
    assert trial == TrialScore(p=1.0, decoy_count=2, beaten=2, tied=0)


def test_a_tied_pair_gets_half_credit() -> None:
    fused = np.asarray([0.5, 0.1, 0.5, 0.5], dtype=np.float32)
    decoys = decoy_set(_index(), _IDS[0])
    trial = rank(fused, _IDS[0], decoys, _index())
    assert trial == TrialScore(p=0.5, decoy_count=2, beaten=0, tied=2)


def test_an_unknown_target_raises() -> None:
    with pytest.raises(ValueError, match="not a member"):
        decoy_set(_index(), "e" * 64)


def test_a_decoy_set_that_holds_the_target_raises() -> None:
    fused = np.zeros(4, dtype=np.float32)
    all_true = np.ones(4, dtype=np.bool_)
    with pytest.raises(ValueError, match="must not contain the target"):
        rank(fused, _IDS[0], all_true, _index())


def test_an_empty_decoy_set_raises() -> None:
    fused = np.zeros(4, dtype=np.float32)
    none = np.zeros(4, dtype=np.bool_)
    with pytest.raises(ValueError, match="empty"):
        rank(fused, _IDS[0], none, _index())
