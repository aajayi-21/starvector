"""Unit: Layer 9 aggregation (spec S1 section 8).

Property tests on seeded Uniform(0, 1) trial scores, the hard-coded
chi-squared reference table, and the section 17 formula shapes.
"""

import math

import numpy as np
import pytest

from core.aggregate import (SkillSummary, chi_squared_tail, fdr_adjusted,
                            shrunk_log_theta, skill_summary)

# Reference values from an offline high-precision computation
# (scipy.stats.chi2.sf, 2026-08-12), 12 digits. The
# (10.96, 24) row is the architecture section 27 worked example:
# its lower tail prints as 0.011 there.
_UPPER_TAIL_REFERENCE = (
    (2.0, 2, 0.367879441171),
    (1.0, 4, 0.909795989569),
    (30.0, 10, 0.000856641210775),
    (10.96, 24, 0.989294280607),
    (24.0, 24, 0.461597333064),
    (50.0, 40, 0.133574834086),
    (800.0, 100, 1.13664078405e-109),
)


def test_chi_squared_tail_agrees_with_reference_values() -> None:
    for statistic, dof, expected in _UPPER_TAIL_REFERENCE:
        assert chi_squared_tail(statistic, dof) == pytest.approx(
            expected, rel=1e-9)


def test_the_worked_example_evidence_value_lands() -> None:
    # Architecture section 27: 2S = 10.96 at 24 degrees of freedom
    # gives evidence 0.011.
    assert 1.0 - chi_squared_tail(10.96, 24) == pytest.approx(0.0107057,
                                                              abs=5e-7)


def test_a_zero_statistic_gives_one() -> None:
    assert chi_squared_tail(0.0, 10) == 1.0


def test_dof_two_is_the_bare_exponential() -> None:
    for statistic in (0.5, 2.0, 7.0):
        assert chi_squared_tail(statistic, 2) == pytest.approx(
            math.exp(-statistic / 2.0), rel=1e-12)


def test_bad_tail_inputs_raise() -> None:
    with pytest.raises(ValueError, match="even"):
        chi_squared_tail(1.0, 3)
    with pytest.raises(ValueError, match="even"):
        chi_squared_tail(1.0, 0)
    with pytest.raises(ValueError, match="not negative"):
        chi_squared_tail(-1.0, 2)
    with pytest.raises(ValueError, match="finite"):
        chi_squared_tail(float("nan"), 2)


def test_uniform_trial_scores_give_a_skill_number_near_one() -> None:
    rng = np.random.default_rng(11)
    ps = rng.uniform(0.0, 1.0, 2000).tolist()
    summary = skill_summary(ps)
    assert isinstance(summary, SkillSummary)
    assert abs(summary.theta - 1.0) < 0.06
    assert summary.n == 2000
    assert summary.dof == 4000
    assert summary.clamp_count == 0


def test_evidence_values_are_uniform_with_no_ability() -> None:
    # 400 seeded no-information players of 20 trials each: the evidence
    # values must themselves agree with Uniform(0, 1). The check is
    # the KS statistic against the 1% asymptotic line.
    rng = np.random.default_rng(7)
    values = sorted(
        skill_summary(rng.uniform(0.0, 1.0, 20).tolist()).evidence_p
        for _ in range(400))
    count = len(values)
    positions = np.arange(1, count + 1, dtype=np.float64)
    ordered = np.asarray(values)
    ks = float(np.maximum(positions / count - ordered,
                          ordered - (positions - 1.0) / count).max())
    assert ks < 1.628 / math.sqrt(count)


def test_a_zero_trial_score_is_clamped_and_counted() -> None:
    summary = skill_summary([0.0, 0.5, 0.9])
    assert summary.clamp_count == 1
    assert math.isfinite(summary.s_statistic)
    assert summary.theta > 0.0


def test_the_unbiased_variant_and_its_minimum_count() -> None:
    ps = [0.4, 0.6, 0.8]
    biased = skill_summary(ps, unbiased=False)
    unbiased = skill_summary(ps, unbiased=True)
    assert biased.theta == pytest.approx(3.0 / biased.s_statistic)
    assert unbiased.theta == pytest.approx(2.0 / biased.s_statistic)
    with pytest.raises(ValueError, match="n >= 2"):
        skill_summary([0.5], unbiased=True)
    assert skill_summary([0.5], unbiased=False).n == 1


def test_out_of_range_and_degenerate_scores_raise() -> None:
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        skill_summary([0.5, 1.5])
    with pytest.raises(ValueError, match="one or more"):
        skill_summary([])
    with pytest.raises(ValueError, match="1.0"):
        skill_summary([1.0, 1.0])


def test_shrinkage_moves_to_the_mean_with_weight_rising_in_n() -> None:
    raw = 0.784
    shrunk = [shrunk_log_theta(raw, n, 0.0, 0.15) for n in (1, 12, 200)]
    # Between the mean and the raw value, and monotone in n.
    assert all(0.0 < value < raw for value in shrunk)
    assert shrunk[0] < shrunk[1] < shrunk[2]
    # The architecture section 27 numbers: n = 12, population_spread 0.15.
    assert shrunk[1] == pytest.approx(12 * 0.784 / (1 / 0.15 ** 2 + 12),
                                      rel=1e-12)
    with pytest.raises(ValueError, match="positive"):
        shrunk_log_theta(raw, 12, 0.0, 0.0)
    with pytest.raises(ValueError, match="at least 1"):
        shrunk_log_theta(raw, 0, 0.0, 0.15)


def test_fdr_adjusted_matches_a_benjamini_hochberg_reference() -> None:
    # Hand-computed: sorted (0.01, 0.02, 0.04, 0.05) at m = 4 gives
    # raw steps (0.04, 0.04, 0.053333, 0.05) and the minimum taken
    # from the top down makes the first and third 0.05.
    adjusted = fdr_adjusted([0.04, 0.01, 0.05, 0.02])
    assert adjusted == pytest.approx((0.05, 0.04, 0.05, 0.04))
    assert fdr_adjusted([]) == ()
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        fdr_adjusted([0.5, 2.0])


def test_the_functions_are_deterministic() -> None:
    ps = [0.31, 0.77, 0.99, 0.45]
    assert skill_summary(ps) == skill_summary(ps)
    assert fdr_adjusted(ps) == fdr_adjusted(ps)
