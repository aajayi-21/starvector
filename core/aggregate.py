"""Layer 9 aggregation: the skill number, evidence, and shrinkage.

Spec: S1 (in docs/specs/) section 8, implementing
docs/ARCHITECTURE.md section 17 as written. Pure functions on trial
scores: no clock, no RNG, no I/O, and population parameters come as
arguments. The layer sits in the no-change tier (CLAUDE.md
section 5) - a formula change here invalidates published numbers.
"""

import math
from collections.abc import Sequence
from typing import NamedTuple


class SkillSummary(NamedTuple):
    """One player's aggregate across n trials (architecture 17).

    theta is the skill number: 1.0 is the no-information baseline,
    above 1.0 says the trial scores cluster high. evidence_statistic is 2S at
    dof = 2n degrees of freedom, and evidence_p is the lower
    chi-squared tail - small values are the evidence direction
    (spec S1 section 14a). clamp_count says how many trial scores
    of 0.0 were clamped before the logarithm.
    """

    n: int
    clamp_count: int
    s_statistic: float
    theta: float
    log_theta: float
    evidence_statistic: float
    dof: int
    evidence_p: float


def chi_squared_tail(statistic: float, dof: int) -> float:
    """The chi-squared tail P(X >= statistic), dof divisible by two.

    For X chi-squared at dof = 2n degrees of freedom the tail is the
    finite Poisson sum exp(-S) * sum_{k<n} S^k / k! at
    S = statistic / 2 - a closed shape, thus no numeric dependency
    (spec S1, R7). The terms collect on the logarithmic scale so a
    statistic in the hundreds keeps its precision. A statistic of
    0.0 gives 1.0. An odd or non-positive dof, a negative statistic,
    or a non-finite input raises.
    """
    if dof < 2 or dof % 2 != 0:
        raise ValueError(f"dof must be a positive even integer, got {dof}")
    if not math.isfinite(statistic) or statistic < 0.0:
        raise ValueError(f"statistic must be finite and not negative, "
                         f"got {statistic!r}")
    if statistic == 0.0:
        return 1.0
    half = statistic / 2.0
    count = dof // 2
    log_half = math.log(half)
    log_terms = [k * log_half - math.lgamma(k + 1) for k in range(count)]
    peak = max(log_terms)
    total = math.fsum(math.exp(term - peak) for term in log_terms)
    return min(1.0, math.exp(peak - half) * total)


def skill_summary(ps: Sequence[float], unbiased: bool = True) -> SkillSummary:
    """The section 17 aggregate of one player's trial scores.

    S is the negative sum of the logarithms of the trial scores.
    theta = n / S, or (n - 1) / S with unbiased (which requires
    n >= 2 - the section 14a ruling: (n - 1) / S at n = 1 is 0, not
    an estimate). A trial score of 0.0 is clamped to the smallest
    positive float and counted - a silent infinity is worse than a
    named clamp. A trial score out of [0, 1] raises,
    and a sequence of all-1.0 scores raises: S = 0 puts the skill
    number out of range, and a silent cap can misstate it.
    """
    scores = [float(p) for p in ps]
    n = len(scores)
    if n == 0:
        raise ValueError("skill_summary needs one or more trial scores")
    if unbiased and n < 2:
        raise ValueError(
            "the unbiased variant needs n >= 2 - (n - 1) / S at n = 1 "
            "is 0, not an estimate (spec S1 section 14a)")
    clamp_count = 0
    terms: list[float] = []
    for p in scores:
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError(f"a trial score must sit in [0, 1], got {p!r}")
        if p == 0.0:
            p = math.ulp(0.0)
            clamp_count += 1
        terms.append(-math.log(p))
    s_statistic = math.fsum(terms)
    if s_statistic == 0.0:
        raise ValueError(
            "each trial score is 1.0 - S is 0 and the skill number is "
            "out of range")
    theta = ((n - 1) if unbiased else n) / s_statistic
    return SkillSummary(
        n=n,
        clamp_count=clamp_count,
        s_statistic=s_statistic,
        theta=theta,
        log_theta=math.log(theta),
        evidence_statistic=2.0 * s_statistic,
        dof=2 * n,
        evidence_p=1.0 - chi_squared_tail(2.0 * s_statistic, 2 * n),
    )


def shrunk_log_theta(log_theta: float, n: int, population_mean: float,
                     population_spread: float) -> float:
    """The section 17 shrinkage of one player's log_theta.

    (population_mean / population_spread^2 + n * log_theta) divided
    by (1 / population_spread^2 + n). The weight on the player's own
    estimate rises with the trial count. Population parameters are arguments (R7): the solo display
    passes the D5 values, and a fitted population comes with live
    players. A non-positive population_spread or a trial count below
    1 raises.
    """
    if not math.isfinite(log_theta):
        raise ValueError(f"log_theta must be finite, got {log_theta!r}")
    if n < 1:
        raise ValueError(f"the trial count must be at least 1, got {n}")
    if not population_spread > 0.0:
        raise ValueError(
            f"population_spread must be positive, got {population_spread!r}")
    precision = 1.0 / (population_spread * population_spread)
    return (population_mean * precision + n * log_theta) / (precision + n)


def fdr_adjusted(p_values: Sequence[float]) -> tuple[float, ...]:
    """Benjamini-Hochberg adjusted values, in the input sequence.

    The section 17 rate adjustment for many players tested at one
    time. adjusted_(i) is the minimum across j >= i of
    (m * p_(j) / j), clamped to 1.0, computed on the ascending
    sequence and mapped back. The trial server ships it for the
    multi-player stage alone. A value out of [0, 1] raises. An empty
    input gives an empty output.
    """
    values = [float(p) for p in p_values]
    for p in values:
        if not math.isfinite(p) or not 0.0 <= p <= 1.0:
            raise ValueError(f"a p-value must sit in [0, 1], got {p!r}")
    m = len(values)
    order = sorted(range(m), key=lambda position: values[position])
    adjusted = [0.0] * m
    running = 1.0
    for rank_position in range(m - 1, -1, -1):
        position = order[rank_position]
        running = min(running, values[position] * m / (rank_position + 1))
        adjusted[position] = running
    return tuple(adjusted)
