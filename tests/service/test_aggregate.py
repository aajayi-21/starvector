"""Unit: Layer 9 aggregation (spec S1 section 8).

Property tests on seeded Uniform(0, 1) trial scores, the hard-coded
chi-squared reference table, and the section 17 formula shapes.
"""

import math

import numpy as np
import pytest

from core.aggregate import (DISCOVERY_LEVEL, ELIGIBLE_TRIAL_FLOOR,
                            PROVISIONAL_MEAN, PROVISIONAL_SPREAD,
                            PopulationFit, PosteriorRow,
                            SkillSummary, _generalized_q,
                            _reml_score, baseline_check,
                            chi_squared_tail, digamma, fdr_adjusted,
                            fit_population, kolmogorov_tail, log_term,
                            population_point, shrunk_log_theta,
                            anytime_evidence,
                            discovery_report,
                            eligible_trial_floor,
                            posterior_normal, posterior_ranks,
                            recomputed_trial_floor,
                            skill_summary, stopping_monitor,
                            trigamma, variation_report)

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
    with pytest.raises(ValueError, match="positive"):
        chi_squared_tail(1.0, 0)
    with pytest.raises(ValueError, match="positive"):
        chi_squared_tail(1.0, -2)
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


def test_one_perfect_trial_holds_a_term_and_a_whole_run_does_not() -> None:
    """The two questions are different and log_term answers one.

    A trial score of 1.0 gives a term of 0.0, which is a number.
    A player with 1.0 at each trial score has S of zero and no
    skill number, thus skill_summary refuses that sequence. A
    reader that answers the narrow question with the wide one stops
    a reveal for a player who beat each decoy on one day.
    """
    assert log_term(1.0) == (0.0, False)
    assert log_term(0.5) == (-math.log(0.5), False)
    clamped, ran = log_term(0.0)
    assert ran is True
    assert math.isfinite(clamped)
    assert clamped > 700.0
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        log_term(1.5)
    # The wide question keeps its refusal.
    with pytest.raises(ValueError, match="each trial score is 1.0"):
        skill_summary([1.0, 1.0], unbiased=False)
    # One perfect day in a run of others is not a refusal.
    assert skill_summary([1.0, 0.5], unbiased=False).s_statistic \
        == pytest.approx(-math.log(0.5))


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


# ---- spec M1 section 6: the accurate parameterization ----

_GAMMA = 0.5772156649015328606


def test_digamma_and_trigamma_match_their_closed_forms() -> None:
    assert digamma(1.0) == pytest.approx(-_GAMMA, rel=1e-14)
    assert digamma(0.5) == pytest.approx(-_GAMMA - 2.0 * math.log(2.0),
                                         rel=1e-14)
    assert digamma(2.0) == pytest.approx(1.0 - _GAMMA, rel=1e-14)
    assert trigamma(1.0) == pytest.approx(math.pi ** 2 / 6.0, rel=1e-14)
    assert trigamma(0.5) == pytest.approx(math.pi ** 2 / 2.0, rel=1e-14)


@pytest.mark.parametrize("x", [0.3, 1.0, 2.7, 9.9, 40.0])
def test_the_duplication_identities_hold(x: float) -> None:
    # A property that wants no reference table, and the one identity
    # available here: the reflection formula wants x below zero,
    # which these functions refuse.
    assert (0.5 * digamma(x) + 0.5 * digamma(x + 0.5) + math.log(2.0)
            == pytest.approx(digamma(2.0 * x), rel=1e-12))
    assert (0.25 * (trigamma(x) + trigamma(x + 0.5))
            == pytest.approx(trigamma(2.0 * x), rel=1e-12))


@pytest.mark.parametrize("x", [0.5, 1.0, 7.0, 250.0, 1.0e6])
def test_the_recurrence_identities_hold(x: float) -> None:
    # The tolerance is scaled to the operands and not to 1/x. At
    # x = 1e6 the difference is 1e-6 formed from two values near
    # 13.8, thus seven digits cancel by construction and a tighter
    # bound is a flake waiting to occur.
    assert abs((digamma(x + 1.0) - digamma(x)) - 1.0 / x) \
        <= 8.0 * math.ulp(abs(digamma(x)))
    assert abs((trigamma(x) - trigamma(x + 1.0)) - 1.0 / (x * x)) \
        <= 8.0 * math.ulp(abs(trigamma(x)))


@pytest.mark.parametrize("x", [1.0, 2.0, 10.0, 1000.0])
def test_the_asymptotic_brackets_hold(x: float) -> None:
    assert math.log(x) - 1.0 / x < digamma(x) < math.log(x) - 0.5 / x
    assert 1.0 / x + 0.5 / (x * x) < trigamma(x) <= 1.0 / x + 1.0 / (x * x)


def test_the_architecture_quotes_land() -> None:
    # The section 17 change quotes these to two digits, thus the
    # tolerance is the one that fits two digits.
    assert math.log(1.0) - digamma(1.0) == pytest.approx(0.58, abs=5e-3)
    assert math.log(10.0) - digamma(10.0) == pytest.approx(0.05, abs=5e-3)
    assert 1.0 * trigamma(1.0) - 1.0 == pytest.approx(0.64, abs=5e-3)
    assert 3.0 * trigamma(3.0) - 1.0 == pytest.approx(0.18, abs=5e-3)


def test_the_parameterization_functions_are_monotone() -> None:
    ladder = [0.5, 1.0, 2.0, 5.0, 20.0, 100.0]
    assert all(digamma(a) < digamma(b)
               for a, b in zip(ladder, ladder[1:]))
    assert all(trigamma(a) > trigamma(b)
               for a, b in zip(ladder, ladder[1:]))


def test_the_parameterization_refuses_a_pole() -> None:
    for bad in (0.0, -1.0, -0.5, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="positive"):
            digamma(bad)
        with pytest.raises(ValueError, match="positive"):
            trigamma(bad)


def test_the_odd_tail_agrees_with_its_closed_forms() -> None:
    # dof 1 and dof 3 have elementary shapes, thus they pin the odd
    # branch with no reference table.
    for x in (0.1, 0.5, 1.0, 2.0, 3.84, 7.0, 15.0, 40.0):
        assert chi_squared_tail(x, 1) == pytest.approx(
            math.erfc(math.sqrt(x / 2.0)), rel=1e-12)
        expected = (math.erfc(math.sqrt(x / 2.0))
                    + 2.0 * math.sqrt(x / (2.0 * math.pi))
                    * math.exp(-x / 2.0))
        assert chi_squared_tail(x, 3) == pytest.approx(expected, rel=1e-12)


def test_the_tail_rises_with_the_degrees_of_freedom() -> None:
    for x in (150.0, 199.0, 250.0, 300.0):
        assert chi_squared_tail(x, 198) < chi_squared_tail(x, 199) \
            < chi_squared_tail(x, 200)


def _null_points(count: int, low: int, high: int, seed: int,
                 tau: float = 0.0) -> list:
    """Players pulled from the accurate law, at a width of tau."""
    rng = np.random.default_rng(seed)
    rows = []
    for n in rng.integers(low, high + 1, size=count):
        skill = math.exp(tau * rng.standard_normal())
        rows.append(population_point(int(n),
                                     float(rng.gamma(int(n), 1.0 / skill))))
    return rows


def test_the_population_point_carries_the_exact_transform() -> None:
    point = population_point(7, 4.0)
    assert point.y == pytest.approx(digamma(7) - math.log(4.0), rel=1e-14)
    assert point.v == pytest.approx(trigamma(7), rel=1e-14)
    with pytest.raises(ValueError, match="trial count"):
        population_point(0, 1.0)
    with pytest.raises(ValueError, match="positive"):
        population_point(3, 0.0)


def test_the_fit_recovers_a_generated_population() -> None:
    fit = fit_population(_null_points(200, 30, 200, 5, tau=0.20))
    assert fit.fitted is True
    assert 0.15 < fit.tau < 0.25
    assert abs(fit.mu) < 3.0 * fit.mu_spread


def test_the_zero_estimate_is_kept_as_zero() -> None:
    # A fitted width of zero is a correct answer and stays one.
    fit = fit_population(_null_points(400, 30, 200, 7))
    assert fit.fitted is True
    assert fit.tau == 0.0
    assert fit.halvings == 0


def test_the_returned_root_satisfies_the_score_equation() -> None:
    # The honest test of a root: its own equation, not a number
    # copied from somewhere else.
    rows = _null_points(200, 30, 200, 11, tau=0.25)
    fit = fit_population(rows)
    scale = math.fsum(1.0 / (row.v + fit.tau ** 2) for row in rows)
    assert abs(_reml_score(rows, fit.tau ** 2)) <= 1e-9 * scale


def test_the_fit_is_a_function_of_its_input() -> None:
    rows = _null_points(60, 30, 200, 13, tau=0.3)
    assert fit_population(rows) == fit_population(rows)


def test_the_fit_below_the_player_floor_is_provisional() -> None:
    fit = fit_population(_null_points(10, 30, 200, 3))
    assert fit.fitted is False
    assert fit.player_count == 10
    assert (fit.mu, fit.tau) == (PROVISIONAL_MEAN, PROVISIONAL_SPREAD)


def test_the_variation_report_is_four_numbers_and_no_verdict() -> None:
    rows = _null_points(200, 30, 200, 5, tau=0.20)
    report = variation_report(rows, fit_population(rows))
    assert report.dof == 199
    assert report.q_significance < 0.01
    assert report.tau_low < report.tau < (report.tau_high or math.inf)
    assert report.tau_multiplicative == pytest.approx(math.exp(report.tau))
    assert report.prediction_low < report.prediction_high


def test_the_variation_interval_reaches_zero_on_a_flat_population() -> None:
    # The contour method is what stays honest here: a symmetric
    # interval can put the bottom end below zero and say nothing.
    rows = _null_points(200, 30, 200, 7)
    report = variation_report(rows, fit_population(rows))
    assert report.tau == 0.0
    assert report.tau_low == 0.0
    assert report.tau_high is not None and report.tau_high > 0.0
    assert report.q_significance > 0.05


def test_the_profile_ends_satisfy_their_defining_equation() -> None:
    rows = _null_points(200, 30, 200, 5, tau=0.20)
    report = variation_report(rows, fit_population(rows))
    for end, level in ((report.tau_low, 0.025), (report.tau_high, 0.975)):
        assert end is not None
        tail = chi_squared_tail(_generalized_q(rows, end * end), report.dof)
        assert tail == pytest.approx(level, abs=1e-6)


def test_the_baseline_check_passes_the_null_and_fails_skewed_play(
) -> None:
    assert baseline_check(_null_points(300, 30, 200, 9)).significance > 0.01
    rng = np.random.default_rng(4)
    skewed = [population_point(int(n), float(rng.gamma(int(n), 0.6)))
              for n in rng.integers(30, 200, size=300)]
    assert baseline_check(skewed).significance < 1e-6


def test_the_core_and_harness_kolmogorov_values_agree() -> None:
    # core must not import validation, thus this file holds the
    # tail two times, and this test keeps the two together.
    from validation.v2 import ks_significance

    for statistic in (0.01, 0.05, 0.1, 0.2, 0.4):
        for count in (10, 100, 1000):
            assert kolmogorov_tail(statistic, count) == pytest.approx(
                ks_significance(statistic, count), rel=1e-12)


# ---- spec M1 section 6: ranks, evidence, and the monitors ----


def _fixed_fit(tau: float = 0.3) -> PopulationFit:
    return PopulationFit(player_count=50, fitted=True, mu=0.0, tau=tau,
                         mu_spread=0.05, halvings=60)


def test_the_posterior_reads_the_accurate_variance() -> None:
    fit = _fixed_fit()
    point = population_point(12, 12.0)
    row = posterior_normal(point, fit)
    tau_precision = 1.0 / fit.tau ** 2
    own = 1.0 / point.v
    assert row.mean == pytest.approx(
        (fit.mu * tau_precision + point.y * own) / (tau_precision + own),
        rel=1e-12)
    assert row.spread == pytest.approx(
        math.sqrt(1.0 / (tau_precision + own)), rel=1e-12)


def test_a_zero_width_collapses_each_player_onto_the_centre() -> None:
    fit = _fixed_fit(tau=0.0)
    row = posterior_normal(population_point(12, 12.0), fit)
    assert (row.mean, row.spread) == (fit.mu, 0.0)


def _rank_oracle(rows: list[PosteriorRow]) -> list[float]:
    """The closed-shape expected rank, from the bell-curve tail.

    Rank one is the top, thus a player's expected rank is one plus
    the count of players above them in expectation. This wants no
    reference table and no other library, thus it is the strongest
    check available on the simulation.
    """
    out = []
    for own in rows:
        total = 1.0
        for other in rows:
            if other is own:
                continue
            z = ((other.mean - own.mean)
                 / math.sqrt(own.spread ** 2 + other.spread ** 2))
            total += 0.5 * math.erfc(-z / math.sqrt(2.0))
        out.append(total)
    return out


def test_the_sampled_expected_rank_agrees_with_the_closed_shape() -> None:
    fit = _fixed_fit(tau=0.25)
    rows = [posterior_normal(point, fit)
            for point in _null_points(8, 5, 200, 3, tau=0.25)]
    sampled = [row.expected_rank for row in posterior_ranks(rows, seed=42)]
    for got, want in zip(sampled, _rank_oracle(rows)):
        assert got == pytest.approx(want, abs=0.2)


def test_a_low_trial_player_lands_at_the_middle() -> None:
    # The property the rule buys: a lucky short run cannot get the
    # top, and no threshold does the work.
    fit = _fixed_fit()
    strong = math.exp(-0.8)
    low = posterior_normal(population_point(3, 3 * strong), fit)
    high = posterior_normal(population_point(200, 200 * strong), fit)
    others = [posterior_normal(point, fit)
              for point in _null_points(8, 5, 200, 3)]
    ranks = posterior_ranks([low, high] + others, seed=7)
    middle = (len(ranks) + 1) / 2.0
    assert abs(ranks[0].expected_rank - middle) \
        < abs(ranks[1].expected_rank - middle)
    assert (ranks[0].rank_high - ranks[0].rank_low) \
        > (ranks[1].rank_high - ranks[1].rank_low)


def test_the_ranks_are_a_function_of_the_seed() -> None:
    rows = [posterior_normal(point, _fixed_fit())
            for point in _null_points(6, 5, 200, 3)]
    assert posterior_ranks(rows, seed=11) == posterior_ranks(rows, seed=11)


def test_a_zero_width_ties_every_player_at_the_middle() -> None:
    fit = _fixed_fit(tau=0.0)
    rows = [posterior_normal(point, fit)
            for point in _null_points(5, 5, 200, 3)]
    ranks = posterior_ranks(rows, seed=1)
    assert all(row.expected_rank == 3.0 for row in ranks)
    assert all((row.rank_low, row.rank_high) == (1, 5) for row in ranks)


def test_the_rank_interval_holds_the_expected_rank() -> None:
    rows = [posterior_normal(point, _fixed_fit())
            for point in _null_points(10, 5, 200, 3, tau=0.3)]
    for row in posterior_ranks(rows, seed=5):
        assert row.rank_low <= row.expected_rank <= row.rank_high


def test_an_empty_board_ranks_nothing() -> None:
    assert posterior_ranks([], seed=1) == ()


def test_the_evidence_collapses_to_its_closed_shape() -> None:
    # The cut mixture adds the moved constant and the top tail at
    # an integer shape, which chi_squared_tail holds today.
    for n, s in ((1, 0.5), (12, 9.0), (200, 150.0)):
        shifted = s + 1.0
        expected = (s + 1.0 + math.lgamma(n + 1)
                    - (n + 1) * math.log(shifted)
                    + math.log(chi_squared_tail(2.0 * shifted, 2 * (n + 1))))
        assert anytime_evidence(n, s).log_e_value == pytest.approx(
            expected, rel=1e-12)


def test_the_evidence_agrees_with_its_own_integral() -> None:
    """The closed shape against a numeric area below the curve.

    The cut mixture (the 2026-08-16 ruling) is a moved exponential
    on the skills above one, thus the value is the area below the
    likelihood ratio against it. Summing that area by hand is the
    one check that wants no other library and no reference table.
    """
    for n, s in ((3, 1.0), (20, 5.0), (20, 20.0), (50, 30.0)):
        grid = np.linspace(1.0, 1.0 + 400.0 / (s + 1.0), 400001)
        ratio = np.exp(n * np.log(grid) + s * (1.0 - grid) - (grid - 1.0))
        # The tolerance is the trapezoid rule's own error and not
        # the closed shape's: the grid is finite.
        assert anytime_evidence(n, s).log_e_value == pytest.approx(
            math.log(float(np.trapezoid(ratio, grid))), rel=1e-7)


def test_the_evidence_falls_as_the_player_does_worse() -> None:
    """The direction a reader expects: a small S is a high skill.

    The mixture is cut at a skill number of one, thus the value
    answers "is this player above the baseline" and falls from the
    top down. The mixture across each positive skill, which section
    6 pinned before the 2026-08-16 ruling, climbed again below the
    baseline and named a weak run strong evidence.
    """
    values = [anytime_evidence(20, s).log_e_value
              for s in (2.0, 5.0, 10.0, 20.0, 40.0, 100.0)]
    assert values == sorted(values, reverse=True)


def test_the_evidence_records_the_mixture_it_used() -> None:
    summary = anytime_evidence(12, 9.0)
    assert (summary.mixture_shape, summary.mixture_rate) == (1.0, 1.0)
    assert summary.mixture_floor == 1.0
    assert summary.significance == pytest.approx(
        min(1.0, math.exp(-summary.log_e_value)), rel=1e-12)


def test_the_evidence_holds_its_bound_with_no_skill() -> None:
    # Ville's inequality: with no skill the chance the value ever
    # gets to 20 is at or below 1/20.
    #
    # Do NOT check this by the sample mean. The mean with no skill
    # is accurately one and the variance is unbounded, thus the sample
    # mean is not a stable statistic - 20000 values here average
    # 0.615. The bound is the statement that holds.
    rng = np.random.default_rng(5)
    statistics = rng.gamma(25, 1.0, size=20000)
    values = np.array([math.exp(anytime_evidence(25, float(s)).log_e_value)
                       for s in statistics])
    assert float((values >= 20.0).mean()) <= 0.05


def test_the_recomputed_floor_tracks_the_approximate_reading() -> None:
    for tau, approximate in ((0.05, 400), (0.15, 44.4), (0.3, 11.1)):
        assert abs(recomputed_trial_floor(tau) - approximate) <= 1.5
    with pytest.raises(ValueError, match="positive"):
        recomputed_trial_floor(0.0)


def test_the_floor_never_falls_below_the_architecture_figure() -> None:
    # Ruling 9 of 2026-08-15: a recomputation can widen the floor
    # and must not quietly weaken it.
    wide = PopulationFit(player_count=300, fitted=True, mu=0.0, tau=0.3,
                         mu_spread=0.01, halvings=60)
    assert recomputed_trial_floor(0.3) < ELIGIBLE_TRIAL_FLOOR
    assert eligible_trial_floor(wide) == ELIGIBLE_TRIAL_FLOOR
    narrow = PopulationFit(player_count=300, fitted=True, mu=0.0, tau=0.05,
                           mu_spread=0.01, halvings=60)
    assert eligible_trial_floor(narrow) == 401
    small = PopulationFit(player_count=100, fitted=True, mu=0.0, tau=0.05,
                          mu_spread=0.01, halvings=60)
    assert eligible_trial_floor(small) == ELIGIBLE_TRIAL_FLOOR


def test_the_stopping_monitor_separates_clean_play_from_stopping() -> None:
    # The magnitude carries and not the sign: section 6 quotes a
    # positive number and the natural indication gives a negative one.
    clean = _null_points(300, 5, 200, 1)
    assert abs(stopping_monitor(
        clean, fit_population(clean)).correlation) < 4.0 / math.sqrt(300)
    stopped = []
    rng = np.random.default_rng(2)
    for _ in range(300):
        for n in range(3, 200):
            point = population_point(n, float(rng.gamma(n, 1.0)))
            if point.y > 0.6 or n > 150:
                stopped.append(point)
                break
    monitor = stopping_monitor(stopped, fit_population(stopped))
    assert monitor.correlation is not None
    assert abs(monitor.correlation) >= 0.3


def test_the_monitor_says_nothing_when_it_measured_nothing() -> None:
    # A silent zero here can read as clean play.
    rng = np.random.default_rng(8)
    flat = [population_point(40, float(rng.gamma(40, 1.0)))
            for _ in range(30)]
    assert stopping_monitor(flat, fit_population(flat)).correlation is None


def test_the_discovery_report_is_a_natural_frequency() -> None:
    report = discovery_report([0.001] * 3 + [0.5] * 97)
    assert (report.tested, report.flagged) == (100, 3)
    assert report.expected_by_luck == pytest.approx(0.05 * 3)
    assert report.level == 0.05
    with pytest.raises(ValueError, match=r"\(0, 1\)"):
        discovery_report([0.5], level=0.0)
