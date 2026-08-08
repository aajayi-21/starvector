"""Unit tests for the Layer 5 algebra and its ranking properties."""

import numpy as np
import pytest

from core.normalize import commonness_correct, standardize

SEEDS = range(20)


def _ranking(scores: np.ndarray) -> list[int]:
    return list(np.argsort(scores, kind="stable"))


def test_the_correction_formula_is_pinned() -> None:
    raw = np.asarray([1.0, 2.0, 3.0], dtype=np.float32)
    common = np.asarray([0.5, 1.0, 4.0], dtype=np.float32)
    corrected = commonness_correct(raw, common)
    assert corrected == pytest.approx([1.5, 3.0, 2.0])
    assert corrected.dtype == np.float32


def test_a_non_constant_table_changes_the_ranking() -> None:
    raw = np.asarray([1.0, 2.0], dtype=np.float32)
    common = np.asarray([0.0, 10.0], dtype=np.float32)
    assert _ranking(raw) == [0, 1]
    assert _ranking(commonness_correct(raw, common)) == [1, 0]


def test_standardizing_keeps_the_ranking() -> None:
    for seed in SEEDS:
        scores = np.random.default_rng(seed).normal(
            5.0, 3.0, 40).astype(np.float32)
        assert _ranking(standardize(scores)) == _ranking(scores)


def test_a_constant_shift_keeps_the_ranking() -> None:
    for seed in SEEDS:
        scores = np.random.default_rng(seed).normal(
            0.0, 1.0, 40).astype(np.float32)
        shifted = (scores + np.float32(7.5)).astype(np.float32)
        assert _ranking(shifted) == _ranking(scores)
        assert _ranking(standardize(shifted)) == _ranking(scores)


def test_standardize_output_has_mean_zero_and_deviation_one() -> None:
    scores = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    standardized = standardize(scores)
    assert float(standardized.mean()) == pytest.approx(0.0, abs=1e-6)
    assert float(standardized.std(ddof=0)) == pytest.approx(1.0, rel=1e-5)


def test_zero_deviation_raises() -> None:
    scores = np.full(5, 2.5, dtype=np.float32)
    with pytest.raises(ValueError, match="standard deviation is zero"):
        standardize(scores)


def test_length_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        commonness_correct(np.zeros(3, dtype=np.float32),
                           np.zeros(4, dtype=np.float32))


def test_wrong_dtype_raises() -> None:
    with pytest.raises(ValueError, match="float32"):
        standardize(np.zeros(3, dtype=np.float64))


def test_a_non_finite_value_raises() -> None:
    poisoned = np.asarray([1.0, float("nan"), 2.0], dtype=np.float32)
    with pytest.raises(ValueError, match="non-finite"):
        standardize(poisoned)
    with pytest.raises(ValueError, match="non-finite"):
        commonness_correct(poisoned, np.zeros(3, dtype=np.float32))
    with pytest.raises(ValueError, match="non-finite"):
        commonness_correct(np.zeros(3, dtype=np.float32), poisoned)
