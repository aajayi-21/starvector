"""The permanent baseline calibration gate (spec M1 section 12).

Simulated play with no skill anywhere must keep the between-player
test at its nominal level. This is the gate that justifies the
accurate parameterization: with the 1/n approximation the same
simulation fires far above 5 percent, and the distance widens with
the player count.

The trial-count law is not in the spec, so it is recovered here and
recorded. The approximation's inflation multiplier is n
trigamma(n), which averages 1.171 across the counts 1 to 10 and
pushes the statistic from 199 to 233 at 200 players - the 5 percent
point. With that law the numbers agree with the spec's table:

    players   approximation   accurate
        50    22.5% / 25.5%   7.5% / 8.8%
       200    57.0% / 58.5%   6.5% / 8.0%
      1000    97.3% / 97.5%   7.0% / 7.5%

The left value in each pair is the spec's and the right one is what
this file measures.

The band is derived and is not a flake allowance. The count of
fires is a binomial count, thus at 400 replications and a rate of
0.08 the standard deviation is 5.42 counts. Four standard
deviations is 21.7 counts, which is a rate in [0.026, 0.134],
rounded outward to the band below. Four standard deviations is a
two-sided 6e-5, which is what a gate that stands forever wants.

The remaining increase above 5 percent is the shape of y at small
trial counts and is not a defect of the transform: the spec's own
accurate column holds the same increase.

The simulation is seeded, thus the result is fixed. The band says
how far a future edit can move the number before this gate stops
being correct.
"""

import math

import numpy as np
import pytest

from core.aggregate import chi_squared_tail, population_point

_SEED = 777
_TRIAL_LOW, _TRIAL_HIGH = 1, 10
_ACCURATE_BAND = (0.02, 0.14)
# The direction the spec measures, with a wide band: the point is
# the distance and not the third digit.
_APPROXIMATE_FLOOR = {50: 0.20, 200: 0.45, 1000: 0.85}
_REPLICATIONS = {50: 400, 200: 400, 1000: 120}


def _fires(player_count: int, rng: np.random.Generator) -> tuple[bool, bool]:
    """One replication: does each arm's test fire at the 5% level?"""
    counts = rng.integers(_TRIAL_LOW, _TRIAL_HIGH + 1, size=player_count)
    # The accurate no-skill law: S is Gamma at shape n, rate one.
    statistics = rng.gamma(counts, 1.0)

    points = [population_point(int(n), float(s))
              for n, s in zip(counts, statistics)]
    accurate_y = np.array([point.y for point in points])
    accurate_v = np.array([point.v for point in points])

    # The approximation section 17 used to give, written out here so
    # a reader sees the contrast in the test body.
    approximate_y = np.log(counts / statistics)
    approximate_v = 1.0 / counts

    fired = []
    for values, variances in ((accurate_y, accurate_v),
                              (approximate_y, approximate_v)):
        weights = 1.0 / variances
        mean = float((weights * values).sum() / weights.sum())
        statistic = float((weights * (values - mean) ** 2).sum())
        fired.append(chi_squared_tail(statistic, player_count - 1) < 0.05)
    return fired[0], fired[1]


def test_the_baseline_holds_its_nominal_level() -> None:
    rng = np.random.default_rng(_SEED)
    for player_count, replications in _REPLICATIONS.items():
        outcomes = np.array([_fires(player_count, rng)
                             for _ in range(replications)])
        accurate, approximate = outcomes.mean(axis=0)
        low, high = _ACCURATE_BAND
        assert low <= accurate <= high, (
            f"{player_count} players: the accurate arm fired "
            f"{accurate:.1%}, outside [{low:.0%}, {high:.0%}]")
        assert approximate >= _APPROXIMATE_FLOOR[player_count], (
            f"{player_count} players: the approximation fired "
            f"{approximate:.1%}, and the defect wants at least "
            f"{_APPROXIMATE_FLOOR[player_count]:.0%}")
        assert approximate > accurate


def test_the_gap_widens_with_the_player_count() -> None:
    """The defect is not a constant offset - it becomes larger."""
    rng = np.random.default_rng(_SEED)
    rates = []
    for player_count in (50, 200, 1000):
        outcomes = np.array([_fires(player_count, rng)
                             for _ in range(_REPLICATIONS[player_count])])
        rates.append(float(outcomes.mean(axis=0)[1]))
    assert rates[0] < rates[1] < rates[2]


def test_the_inflation_factor_is_the_cause() -> None:
    """n trigamma(n) is why the approximation fires (section 6).

    The approximation calls the variance 1/n where it is
    trigamma(n), thus each term of the statistic is scaled by
    n trigamma(n). Its mean across the trial-count law is the
    quantity that moves the statistic off its degrees of freedom.
    """
    from core.aggregate import trigamma

    scales = [n * trigamma(n)
              for n in range(_TRIAL_LOW, _TRIAL_HIGH + 1)]
    mean_scale = math.fsum(scales) / len(scales)
    assert mean_scale == pytest.approx(1.171, abs=5e-3)
    # 199 degrees of freedom at that scale land on the 5% point,
    # which is 232.9.
    assert 199 * mean_scale == pytest.approx(233.0, abs=2.0)
    # The scale falls to one, thus a population of heavy players
    # can hide the defect - and this game's players are not heavy
    # at the start.
    assert scales[0] > scales[-1] > 1.0
