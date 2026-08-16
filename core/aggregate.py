"""Layer 9 aggregation: the skill number, evidence, and shrinkage.

Spec: S1 (in docs/specs/) section 8, implementing
docs/ARCHITECTURE.md section 17 as written. Pure functions on trial
scores: no clock, no RNG, no I/O, and population parameters come as
arguments. The layer sits in the no-change tier (CLAUDE.md
section 5) - a formula change here invalidates published numbers.

The population half of section 17 (spec M1 in docs/specs/, section
6) lands in this module and not in validation/. The fit reads live
player pairs, thus the gate that isolates the fitting code refuses it on
that side, and core is the trusted package that gate names. I6 governs
the fitting of channel weights on live trials with the target as
the label. This module fits one population width across stored
trials, and it sees no label, no weight, and no encoder. Ruling 9
of spec M1 and the section 17 change of 2026-08-15 authorize it.

Each function here uses math alone. The one function that wants an
array is posterior_ranks, and it says so in its own docstring.
"""

import math
from collections.abc import Sequence
from typing import NamedTuple

# The recurrence pushes an argument to the threshold, then the
# Bernoulli series runs. The term count is fixed and the walk
# count is ceil(threshold - x), a closed function of the argument.
# No count here is a convergence test, because a convergence test
# makes the output a function of floating-point noise, and two runs
# must give equal bytes (the rule at core/channels/element.py).
#
# Trigamma sets the threshold: its series decays one power slower
# than digamma's. At 15 the first term nobody adds is about
# 2.7e-18 for the two, which is below one unit in the last digit.
_ASYMPTOTIC_SHIFT = 15.0

# B(2k)/(2k) for digamma, and B(2k) for trigamma, k = 1 to 6.
_DIGAMMA_TERMS = (1.0 / 12.0, -1.0 / 120.0, 1.0 / 252.0,
                  -1.0 / 240.0, 1.0 / 132.0, -691.0 / 32760.0)
_TRIGAMMA_TERMS = (1.0 / 6.0, -1.0 / 30.0, 1.0 / 42.0,
                   -1.0 / 30.0, 5.0 / 66.0, -691.0 / 2730.0)

# The restricted maximum likelihood root runs a fixed count of
# halvings on a bracket, and not a tolerance loop, for the cause
# above. 60 halvings put the last bracket at about 8.7e-19 of its
# start, which is eleven orders below the six decimals an artifact
# records.
_REML_HALVINGS = 60

# The contour bracket is a grid of powers of two, then the same
# halvings: "a grid, no optimizer", one scheme used two times.
_PROFILE_LOW, _PROFILE_HIGH = -20, 40

# The alternating Kolmogorov series, cut at a fixed term count for
# the same cause each count here is fixed.
_KOLMOGOROV_TERMS = 100

# Spec M1 section 6. The two floors are different quantities and
# hold different names on purpose: one counts a player's trials
# and one counts the players who are eligible.
ELIGIBLE_TRIAL_FLOOR = 30
FIT_PLAYER_FLOOR = 30
PUBLISHABLE_PLAYER_COUNT = 200

# The fixed pair below the player floor, and the D5 solo display
# values (spec S1 section 14a).
PROVISIONAL_MEAN = 0.0
PROVISIONAL_SPREAD = 0.15


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


def digamma(x: float) -> float:
    """The logarithmic derivative of the gamma function, x > 0.

    The recurrence walks the argument to the threshold, then six
    Bernoulli terms finish it. Measured against known
    values, the error stays at or below 5e-16 absolute for x >= 0.3.

    The uncertainty of the skill number wants this function and not
    the 1/n approximation section 17 used to give. With the
    approximation the between-player test fires far above its
    nominal level, and the measured table sits in spec M1 section 6.

    A non-positive or non-finite argument raises: the function has
    poles at zero and at each negative integer.
    """
    if not math.isfinite(x) or x <= 0.0:
        raise ValueError(f"digamma wants a finite positive argument, "
                         f"got {x!r}")
    total = 0.0
    y = float(x)
    while y < _ASYMPTOTIC_SHIFT:
        total -= 1.0 / y
        y += 1.0
    inverse_square = 1.0 / (y * y)
    power = inverse_square
    series = 0.0
    for coefficient in _DIGAMMA_TERMS:
        series += coefficient * power
        power *= inverse_square
    return total + math.log(y) - 0.5 / y - series


def trigamma(x: float) -> float:
    """The derivative of digamma, x > 0.

    trigamma(n) is the variance of the logarithm of a Gamma value at
    shape n, thus it is the uncertainty of one player's skill
    number (spec M1 section 6). It runs the same recurrence and the
    same fixed six terms as digamma.

    Each term the series adds is positive, thus the sum holds no
    cancellation. A non-positive or non-finite argument raises.
    """
    if not math.isfinite(x) or x <= 0.0:
        raise ValueError(f"trigamma wants a finite positive argument, "
                         f"got {x!r}")
    total = 0.0
    y = float(x)
    while y < _ASYMPTOTIC_SHIFT:
        total += 1.0 / (y * y)
        y += 1.0
    inverse_square = 1.0 / (y * y)
    power = inverse_square
    series = 0.0
    for coefficient in _TRIGAMMA_TERMS:
        series += coefficient * power
        power *= inverse_square
    return total + 1.0 / y + 0.5 * inverse_square + series / y


def chi_squared_tail(statistic: float, dof: int) -> float:
    """The chi-squared tail P(X >= statistic), dof of one or more.

    For a dof of 2n the tail is the finite Poisson sum
    exp(-S) * sum_{k<n} S^k / k! at S = statistic / 2 - a closed
    shape, thus no numeric dependency (spec S1, R7). The terms
    collect on the logarithmic scale so a statistic in the hundreds
    keeps its precision.

    An odd dof runs the same finite recurrence from a different
    start: it begins at erfc(sqrt(S)) and not at exp(-S). The two
    branches have
    different shapes, and the cause matters. The first moves
    exp(-S)
    out of the sum, thus its terms become large and want the peak
    removed. The odd one keeps -S in each exponent, where each term
    is a weight below one and the total is a probability, thus it
    wants no peak and a large statistic goes to 0.0 in one
    direction.

    The variation report of spec M1 section 6 runs at
    players - 1 degrees of freedom, which is odd one time in two.
    The first branch does not move: its numbers are published.

    A non-positive dof, a negative statistic, or a non-finite input
    raises.
    """
    if dof < 1:
        raise ValueError(f"dof must be a positive integer, got {dof}")
    if not math.isfinite(statistic) or statistic < 0.0:
        raise ValueError(f"statistic must be finite and not negative, "
                         f"got {statistic!r}")
    if statistic == 0.0:
        return 1.0
    half = statistic / 2.0
    if dof % 2 == 0:
        count = dof // 2
        log_half = math.log(half)
        log_terms = [k * log_half - math.lgamma(k + 1) for k in range(count)]
        peak = max(log_terms)
        total = math.fsum(math.exp(term - peak) for term in log_terms)
        return min(1.0, math.exp(peak - half) * total)
    log_half = math.log(half)
    shapes = [0.5 + k for k in range(dof // 2)]
    terms = [math.exp(shape * log_half - half - math.lgamma(shape + 1.0))
             for shape in shapes]
    return min(1.0, math.erfc(math.sqrt(half)) + math.fsum(terms))


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


class PopulationPoint(NamedTuple):
    """One player on the population scale (spec M1 section 6).

    y is the accurate estimate of log_theta, digamma(n) less the
    logarithm of S, and v is its variance, trigamma(n). The two
    letters are the ones the section 17 change uses, thus a reader
    who holds the document can grep for them.
    """

    n: int
    s_statistic: float
    y: float
    v: float


def population_point(n: int, s_statistic: float) -> PopulationPoint:
    """The accurate transform of one player's pair (section 17).

    With the no-skill law S is a Gamma value at shape n and rate
    one, thus the logarithm of S has mean digamma(n) and variance
    trigamma(n). y and v follow, and they are unbiased at each
    trial count. The 1/n approximation is biased at small n, which
    is what breaks the between-player test (spec M1 section 6).

    A trial count below one raises. An S statistic at or below zero
    raises: a player with 1.0 at each trial score has no estimate
    on this scale, and a silent value is worse than the stop.
    """
    if n < 1:
        raise ValueError(f"the trial count must be at least 1, got {n}")
    if not math.isfinite(s_statistic) or s_statistic <= 0.0:
        raise ValueError(f"the S statistic must be finite and positive, "
                         f"got {s_statistic!r}")
    return PopulationPoint(n=n, s_statistic=s_statistic,
                           y=digamma(n) - math.log(s_statistic),
                           v=trigamma(n))


class PopulationFit(NamedTuple):
    """The fitted population of log_theta (spec M1 section 6).

    mu is the centre and tau is the width between players, the two
    of them on the log_theta scale. fitted says the fit ran: below the player
    floor the pair is the declared provisional one and the board
    labels it. mu_spread is the standard error of mu at the
    returned tau.
    """

    player_count: int
    fitted: bool
    mu: float
    tau: float
    mu_spread: float
    halvings: int


def _weighted_mean(points: Sequence[PopulationPoint],
                   s: float) -> tuple[float, float, float]:
    """The weighted mean at variance s, with the two weight sums."""
    weights = [1.0 / (point.v + s) for point in points]
    total = math.fsum(weights)
    mean = math.fsum(w * point.y
                     for w, point in zip(weights, points)) / total
    return mean, total, math.fsum(w * w for w in weights)


def _reml_score(points: Sequence[PopulationPoint], s: float) -> float:
    """The restricted likelihood score at variance s.

    Sum of w^2 (y - mu)^2, less sum of w, plus sum of w^2 divided
    by sum of w. The derivative of mu drops out of the derivation,
    because sum of w (y - mu) is zero by the definition of mu. That
    is why the full fit is one root in one unknown and wants no
    optimizer.
    """
    mean, total, square_total = _weighted_mean(points, s)
    weighted = math.fsum(
        (1.0 / (point.v + s)) ** 2 * (point.y - mean) ** 2
        for point in points)
    return weighted - total + square_total / total


def fit_population(points: Sequence[PopulationPoint], *,
                   player_floor: int = FIT_PLAYER_FLOOR,
                   provisional_mean: float = PROVISIONAL_MEAN,
                   provisional_spread: float = PROVISIONAL_SPREAD,
                   ) -> PopulationFit:
    """Fit mu and tau by restricted maximum likelihood.

    A score at or below zero at s = 0 means the restricted
    likelihood falls away from the boundary, thus the answer is the
    boundary and tau is 0.0. A fitted tau of zero is a correct
    answer and it stays as one: the players are not distinguishable
    at this time (spec M1 section 6).

    Above the boundary the root sits in a bracket the data gives.
    With SS the unweighted sum of squares and m the player count,
    use s_hi = 2 max(v) + 2 (m + 1) SS / (m - 1). Three steps show
    the score is at or below zero there:

    1. Sum of w^2 (y - mu)^2 is at or below w_max^2 sum of
       (y - mu)^2, because each weight is at or below w_max.
    2. Sum of (y - mu)^2 is at or below (m + 1) SS, because mu is a
       weighted mean and thus sits between the smallest and the
       largest y.
    3. Sum of w less sum of w^2 divided by sum of w is at or above
       (m - 1) w_min, because sum of w^2 divided by sum of w is at
       or below w_max.

    Together the score is at or below (m + 1) SS / s^2 less
    (m - 1) / (v_max + s), and at s of 2 v_max or more the second
    term is at or above (m - 1) / (1.5 s). Measured on 3405
    generated sets across trial counts and widths, the bracket held
    each time.

    The bisection runs a fixed count of halvings and no tolerance
    test. The score can have more than one peak. The bisection
    answers the root its sign change holds, and that value is a
    function of the data in each condition.

    Below player_floor the fit does not run. The answer then holds
    the declared provisional pair and marks it not fitted. Fewer than two
    points at or above the floor raises, and so does a point with a
    non-finite y or a variance at or below zero.
    """
    rows = list(points)
    count = len(rows)
    if count < player_floor:
        return PopulationFit(player_count=count, fitted=False,
                             mu=provisional_mean, tau=provisional_spread,
                             mu_spread=0.0, halvings=0)
    if count < 2:
        raise ValueError("the fit wants two or more players")
    for point in rows:
        if not math.isfinite(point.y):
            raise ValueError(f"a population point wants a finite y, "
                             f"got {point.y!r}")
        if not point.v > 0.0:
            raise ValueError(f"a population point wants a positive "
                             f"variance, got {point.v!r}")
    if _reml_score(rows, 0.0) <= 0.0:
        mean, total, _square = _weighted_mean(rows, 0.0)
        return PopulationFit(player_count=count, fitted=True, mu=mean,
                             tau=0.0, mu_spread=1.0 / math.sqrt(total),
                             halvings=0)
    plain_mean = math.fsum(point.y for point in rows) / count
    sum_squares = math.fsum((point.y - plain_mean) ** 2 for point in rows)
    high = (2.0 * max(point.v for point in rows)
            + 2.0 * (count + 1) * sum_squares / (count - 1))
    low = 0.0
    for _ in range(_REML_HALVINGS):
        middle = 0.5 * (low + high)
        if _reml_score(rows, middle) > 0.0:
            low = middle
        else:
            high = middle
    variance = 0.5 * (low + high)
    mean, total, _square = _weighted_mean(rows, variance)
    return PopulationFit(player_count=count, fitted=True, mu=mean,
                         tau=math.sqrt(variance),
                         mu_spread=1.0 / math.sqrt(total),
                         halvings=_REML_HALVINGS)


class VariationReport(NamedTuple):
    """Four numbers about the variation between players, no verdict.

    tau_high is None when no bracket point gets to the level. That
    is the unbounded-above answer of the literature and a defined
    output. tau_multiplicative is exp(tau), the width a player can
    read.
    """

    player_count: int
    q_statistic: float
    dof: int
    q_significance: float
    tau: float
    tau_low: float
    tau_high: float | None
    tau_multiplicative: float
    prediction_low: float
    prediction_high: float


def _generalized_q(points: Sequence[PopulationPoint], s: float) -> float:
    """The weighted sum of squares at variance s."""
    mean, _total, _square = _weighted_mean(points, s)
    return math.fsum((point.y - mean) ** 2 / (point.v + s)
                     for point in points)


def _profile_end(points: Sequence[PopulationPoint], level: float,
                 dof: int) -> float | None:
    """The variance with its weighted sum of squares at the level.

    The generalized statistic falls as the variance rises, thus its
    top tail rises, thus one bracket point holds the answer. The
    bracket is a grid of powers of two and the root is the same
    fixed count of halvings: a grid, no optimizer.

    None says no grid point gets to the level, which reads as
    unbounded above.
    """
    scale = math.fsum(point.v for point in points) / len(points)

    def tail(s: float) -> float:
        return chi_squared_tail(_generalized_q(points, s), dof)

    if tail(0.0) >= level:
        return 0.0
    low = 0.0
    for power in range(_PROFILE_LOW, _PROFILE_HIGH + 1):
        high = scale * (2.0 ** power)
        if tail(high) >= level:
            for _ in range(_REML_HALVINGS):
                middle = 0.5 * (low + high)
                if tail(middle) < level:
                    low = middle
                else:
                    high = middle
            return 0.5 * (low + high)
        low = high
    return None


def variation_report(points: Sequence[PopulationPoint],
                     fit: PopulationFit) -> VariationReport:
    """The variation between players, as four numbers (section 6).

    The statistic is the weighted sum of squares at fixed-effect
    weights, on players - 1 degrees of freedom, and the
    significance is its top tail. Note the direction: this is the
    top tail, and the evidence value of one player is the bottom
    one.

    The interval for tau comes from the contour of that statistic,
    which is the method that stays honest at a fitted tau of zero.
    A symmetric interval can put the bottom end below zero there
    and say nothing.

    There is no I squared here. It is a function of precision, thus
    it climbs when players simply play more, and the trial count in
    this game is a behavior.

    A statistic that does not clear its level is not evidence that
    the players are the same, and the copy must not say that it is.

    The prediction interval is mu plus and minus 1.96 tau, the
    shape spec M1 section 6 pins. The interval of the literature is
    wider and covers better at a small player count. The spec's
    shape ships, and this note records the divergence.

    Fewer than two points raises.
    """
    rows = list(points)
    count = len(rows)
    if count < 2:
        raise ValueError("the variation report wants two or more players")
    dof = count - 1
    q_statistic = _generalized_q(rows, 0.0)
    return VariationReport(
        player_count=count,
        q_statistic=q_statistic,
        dof=dof,
        q_significance=chi_squared_tail(q_statistic, dof),
        tau=fit.tau,
        tau_low=math.sqrt(_profile_end(rows, 0.025, dof) or 0.0),
        tau_high=(None if (high := _profile_end(rows, 0.975, dof)) is None
                  else math.sqrt(high)),
        tau_multiplicative=math.exp(fit.tau),
        prediction_low=fit.mu - 1.96 * fit.tau,
        prediction_high=fit.mu + 1.96 * fit.tau,
    )


class BaselineCheck(NamedTuple):
    """The goodness-of-fit against the no-skill law (section 6)."""

    player_count: int
    statistic: float
    significance: float


def kolmogorov_tail(statistic: float, count: int) -> float:
    """The asymptotic Kolmogorov tail at a sample count.

    The alternating series at the scaled statistic, cut at a fixed
    term count for the cause each count here is fixed. This
    duplicates the harness function of the same shape, because core
    must not import from validation. The test that holds the two
    together compares them across a ladder of statistics.
    """
    if count < 1:
        raise ValueError(f"the sample count must be at least 1, got {count}")
    if not math.isfinite(statistic) or statistic < 0.0:
        raise ValueError(f"the statistic must be finite and not negative, "
                         f"got {statistic!r}")
    scaled = math.sqrt(count) * statistic
    if scaled <= 0.0:
        return 1.0
    total = math.fsum((-1.0) ** (k - 1)
                      * math.exp(-2.0 * k * k * scaled * scaled)
                      for k in range(1, _KOLMOGOROV_TERMS + 1))
    return min(1.0, max(0.0, 2.0 * total))


def baseline_check(points: Sequence[PopulationPoint]) -> BaselineCheck:
    """Compare the stored pairs against the law with no skill.

    With the no-skill law S is a Gamma value at shape n and rate
    one for each player, thus the top tail of 2S at 2n degrees of
    freedom is constant on the unit interval at each trial count.
    That transform is the one shape which handles trial counts that
    are different, and the check is then the two-sided Kolmogorov
    statistic against the flat law.

    A disagreement says the pipeline broke the uniformity the
    ranking guarantees. That is an audit of the guarantee and not a
    tuning task (spec M1 section 6).

    An empty input raises.
    """
    rows = list(points)
    count = len(rows)
    if count < 1:
        raise ValueError("the baseline check wants one or more players")
    values = sorted(chi_squared_tail(2.0 * point.s_statistic, 2 * point.n)
                    for point in rows)
    statistic = max(
        max((index + 1) / count - value, value - index / count)
        for index, value in enumerate(values))
    return BaselineCheck(player_count=count, statistic=statistic,
                         significance=kolmogorov_tail(statistic, count))


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
