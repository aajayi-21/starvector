"""Unit tests for the pure Kolmogorov-Smirnov code (D11)."""

import math

import pytest

from validation.v2 import ks_significance, ks_statistic


def test_the_statistic_on_the_centered_grid_is_exact() -> None:
    assert ks_statistic([0.1, 0.3, 0.5, 0.7, 0.9]) == pytest.approx(
        0.1, abs=1e-12)


def test_the_statistic_ignores_input_sequence() -> None:
    assert ks_statistic([0.9, 0.1, 0.5]) == ks_statistic([0.1, 0.5, 0.9])


def test_the_five_percent_line_at_500_trials() -> None:
    # The asymptotic 5% critical value is 1.3581 / sqrt(n).
    statistic = 1.3581 / math.sqrt(500)
    assert ks_significance(statistic, 500) == pytest.approx(0.05, abs=1e-3)


def test_significance_decreases_as_the_statistic_grows() -> None:
    values = [ks_significance(d, 100) for d in (0.02, 0.05, 0.1, 0.2, 0.4)]
    assert values == sorted(values, reverse=True)


def test_a_zero_statistic_gives_significance_one() -> None:
    assert ks_significance(0.0, 100) == 1.0


def test_an_empty_score_set_raises() -> None:
    with pytest.raises(ValueError, match="no scores"):
        ks_statistic([])
