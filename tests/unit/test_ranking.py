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


# ---- spec AG1 section 5: the day rank ----


def _pool(count: int, duplicates: dict[int, int]) -> PoolIndex:
    """A pool of count images. duplicates maps a position to the position
    of the near-duplicate group that it joins."""
    ids = tuple(f"{position:064x}" for position in range(count))
    groups = [ids[duplicates.get(position, position)]
              for position in range(count)]
    return make_pool_index(
        index_id="e" * 64, image_ids=ids,
        outline_vectors=np.zeros((count, 6, 2), dtype=np.float32),
        outline_space_mean=np.zeros(2, dtype=np.float32),
        group_ids=tuple(groups))


def _brute_day_numbers(scores: np.ndarray, index: PoolIndex) -> np.ndarray:
    """A(t) by the definition: rank() for each player and each candidate."""
    days = []
    for candidate in index.image_ids:
        decoys = decoy_set(index, candidate)
        corrected = []
        for row in scores:
            trial = rank(row, candidate, decoys, index)
            corrected.append((trial.beaten + 0.5 * trial.tied + 0.5)
                             / (trial.decoy_count + 1))
        days.append(np.mean(corrected))
    return np.asarray(days)


def test_the_day_rank_agrees_with_the_definition() -> None:
    from core.ranking import day_rank

    index = _pool(12, {1: 0, 5: 4, 6: 4})
    rng = np.random.default_rng(2)
    # Integer scores, thus equal scores and equal day numbers occur.
    scores = rng.integers(0, 5, size=(4, 12)).astype(np.float32)
    days = _brute_day_numbers(scores, index)
    for position, target in enumerate(index.image_ids):
        lower = int(np.count_nonzero(days < days[position]))
        level = int(np.count_nonzero(days == days[position])) - 1
        expected = (lower + 0.5 * level + 0.5) / 12
        assert day_rank(scores, target, index) == pytest.approx(expected)


def test_the_day_rank_is_flat_with_correlated_players() -> None:
    # 400 days of a pool of 150 images, 25 players, and a strong shared
    # term on each day: the image scores of the players move together.
    # The target is an equally likely member of the pool, and the day
    # ranks agree with the flat law.
    from core.aggregate import day_check
    from core.ranking import day_rank

    index = _pool(150, {7: 3, 9: 3, 40: 41})
    rng = np.random.default_rng(8)
    ranks = []
    for _ in range(400):
        shared = rng.standard_normal(150)
        scores = (0.8 * shared + 0.6 * rng.standard_normal((25, 150))
                  ).astype(np.float32)
        target = index.image_ids[int(rng.integers(0, 150))]
        ranks.append(day_rank(scores, target, index))
    assert day_check(ranks).significance > 0.01


def test_a_target_that_each_player_puts_first_ranks_near_one() -> None:
    from core.ranking import day_rank

    index = _pool(60, {})
    rng = np.random.default_rng(1)
    scores = rng.standard_normal((10, 60)).astype(np.float32)
    scores[:, 17] = 10.0
    assert day_rank(scores, index.image_ids[17], index) > 0.98


def test_the_day_rank_refuses_bad_scores() -> None:
    from core.ranking import day_rank

    index = _pool(6, {})
    with pytest.raises(ValueError, match="shape"):
        day_rank(np.zeros((2, 5), dtype=np.float32), index.image_ids[0],
                 index)
    with pytest.raises(ValueError, match="shape"):
        day_rank(np.zeros((0, 6), dtype=np.float32), index.image_ids[0],
                 index)
    bad = np.zeros((2, 6), dtype=np.float32)
    bad[0, 3] = np.nan
    with pytest.raises(ValueError, match="finite"):
        day_rank(bad, index.image_ids[0], index)
