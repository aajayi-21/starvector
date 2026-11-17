"""The Layer 9 null and power simulations of spec AG1 section 2.

    uv run python -m validation.aggregate_null --reps 200

The rows of the table in docs/specs/aggregation-repairs.md section 2
come from this module and a seed. Each row compares the first format of
Layer 9 with the repaired one:

- the variation report and the baseline check, with no skill, with the
  trial score and its clamp and with the corrected score.
- the power of the two directions against occasional first positions
  and against a constant edge, and the rate of alarms with no skill.
- the baseline check of the players and the day check of the day ranks,
  with no skill and a correlation of the players on each day.

The first format is gone from core/aggregate.py. This module keeps a
copy of its clamp and of its baseline check to compare against alone,
and no score path imports it. A harness runs by hand and its numbers
go in a record (CLAUDE.md section 9).
"""

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from typing import NamedTuple

import numpy as np

from core import aggregate
from core.ranking import day_rank
from core.types import TrialCounts

LEVEL = 0.05


@dataclass(frozen=True, slots=True)
class NullConfig:
    """The values of one run. The defaults give the rows of section 2."""

    seed: int = 20261116
    decoys: int = 1392
    players: int = 200
    days: int = 100
    attendance: float = 0.6
    reps: int = 200
    power_trials: int = 100
    power_reps: int = 2000
    hit_rate: float = 0.05
    edge_theta: float = 1.25
    day_pool: int = 200
    day_players: int = 60
    day_season: int = 60
    correlations: tuple[float, ...] = (0.02, 0.10)


def _first_format_term(beaten: int, decoys: int) -> float:
    """The term of the first format, with a zero clamped.

    The term is the negative logarithm of beaten / D. The clamp read a
    trial score of 0.0 as the smallest positive float, a term of 744.44.
    Kept here to compare against alone.
    """
    p = beaten / decoys
    return -math.log(math.ulp(0.0)) if p == 0.0 else -math.log(p)


def _first_format_baseline(points: list[aggregate.PopulationPoint]) -> float:
    """The significance of the baseline check that spec AG1 replaced.

    The two-sided Kolmogorov statistic of the chi-squared tail of each
    player against the flat law, each player one sample.
    """
    values = sorted(aggregate.chi_squared_tail(2.0 * point.s_statistic,
                                               2 * point.n)
                    for point in points)
    count = len(values)
    statistic = max(max((index + 1) / count - value, value - index / count)
                    for index, value in enumerate(values))
    return aggregate.kolmogorov_tail(statistic, count)


def _beaten_counts(rng: np.random.Generator, count: int, decoys: int,
                   shared: np.ndarray | None, rho: float) -> np.ndarray:
    """No-skill beaten counts. shared adds a day term of weight rho."""
    from math import erf

    z = rng.standard_normal(count)
    if shared is not None:
        z = math.sqrt(1.0 - rho) * z + math.sqrt(rho) * shared
    u = 0.5 * (1.0 + np.vectorize(erf)(z / math.sqrt(2.0)))
    return np.minimum((u * (decoys + 1)).astype(int), decoys)


def population_rates(config: NullConfig, *, corrected: bool,
                     rho: float = 0.0,
                     attendance: float = 1.0) -> dict[str, float]:
    """The share of seasons where each population test fires at 5%."""
    rng = np.random.default_rng(config.seed)
    fired = {"variation": 0, "baseline": 0}
    for _ in range(config.reps):
        day_terms = rng.standard_normal(config.days)
        points = []
        for _ in range(config.players):
            mask = rng.random(config.days) < attendance
            n = int(mask.sum())
            if n < aggregate.ELIGIBLE_TRIAL_FLOOR:
                continue
            beaten = _beaten_counts(rng, n, config.decoys,
                                    day_terms[mask] if rho else None, rho)
            if corrected:
                s_statistic = math.fsum(aggregate.trial_terms(TrialCounts(
                    beaten=int(b), tied=0, decoy_count=config.decoys))[0]
                    for b in beaten)
            else:
                s_statistic = math.fsum(
                    _first_format_term(int(b), config.decoys) for b in beaten)
            points.append(aggregate.population_point(n, s_statistic))
        fit = aggregate.fit_population(points)
        if aggregate.variation_report(points, fit).q_significance < LEVEL:
            fired["variation"] += 1
        if _first_format_baseline(points) < LEVEL:
            fired["baseline"] += 1
    return {name: count / config.reps for name, count in fired.items()}


def _corrected(beaten: np.ndarray, decoys: int) -> np.ndarray:
    return (beaten + 0.5) / (decoys + 1)


def power_rows(config: NullConfig) -> dict[str, dict[str, float]]:
    """The power at 5% of each statistic, by simulated limit values."""
    rng = np.random.default_rng(config.seed)
    n, decoys = config.power_trials, config.decoys

    def null(count: int) -> np.ndarray:
        return _corrected(rng.integers(0, decoys + 1, count), decoys)

    def hits(count: int) -> np.ndarray:
        beaten = rng.integers(0, decoys + 1, count)
        beaten[rng.random(count) < config.hit_rate] = decoys
        return _corrected(beaten, decoys)

    def edge(count: int) -> np.ndarray:
        u = rng.random(count) ** (1.0 / config.edge_theta)
        return _corrected(np.minimum((u * (decoys + 1)).astype(int), decoys),
                          decoys)

    def s_of(p: np.ndarray) -> float:
        return float(-np.log(p).sum())

    def t_of(p: np.ndarray) -> float:
        return float(-np.log1p(-p).sum())

    null_s = np.array([s_of(null(n)) for _ in range(3 * config.power_reps)])
    null_t = np.array([t_of(null(n)) for _ in range(3 * config.power_reps)])
    s_one = float(np.quantile(null_s, LEVEL))
    t_one = float(np.quantile(null_t, 1.0 - LEVEL))
    s_half = float(np.quantile(null_s, LEVEL / 2.0))
    t_half = float(np.quantile(null_t, 1.0 - LEVEL / 2.0))
    rows: dict[str, dict[str, float]] = {}
    for name, alternative in (("strong_hits", hits), ("constant_edge", edge),
                              ("no_skill", null)):
        draws = [alternative(n) for _ in range(config.power_reps)]
        rows[name] = {
            "skill_side": float(np.mean([s_of(p) < s_one for p in draws])),
            "hit_side": float(np.mean([t_of(p) > t_one for p in draws])),
            "two_directions": float(np.mean(
                [s_of(p) < s_half or t_of(p) > t_half for p in draws])),
        }
    return rows


class _DayPool(NamedTuple):
    """The two fields of a pool that day_rank reads, for the day rows.

    A full pool index holds the element and outline sides too, which
    the day rank does not read. Each image is its own group here.
    """

    image_ids: tuple[str, ...]
    group_ids: tuple[str, ...]


def _flat_pool(count: int) -> _DayPool:
    ids = tuple(f"{position:064x}" for position in range(count))
    return _DayPool(image_ids=ids, group_ids=ids)


def day_level_rate(config: NullConfig, rho: float) -> float:
    """The share of seasons where the day check fires, with no skill.

    Each day draws one shared image term and a term for each player and
    image. rho is the correlation of two players' scores of one image.
    The target is an equally likely image, and its day rank comes from
    Layer 8.
    """
    rng = np.random.default_rng(config.seed)
    index = _flat_pool(config.day_pool)
    fired = 0
    for _ in range(config.reps):
        ranks = []
        for _ in range(config.day_season):
            shared = rng.standard_normal(config.day_pool)
            scores = (math.sqrt(rho) * shared + math.sqrt(1.0 - rho)
                      * rng.standard_normal((config.day_players,
                                             config.day_pool))
                      ).astype(np.float32)
            target = index.image_ids[int(rng.integers(0, config.day_pool))]
            ranks.append(day_rank(scores, target, index))  # type: ignore[arg-type]
        if aggregate.day_check(ranks).significance < LEVEL:
            fired += 1
    return fired / config.reps


def run(config: NullConfig) -> dict:
    """Each row of section 2, as one record."""
    record: dict = {"config": asdict(config)}
    record["no_skill"] = {
        "first_format": population_rates(config, corrected=False),
        "corrected": population_rates(config, corrected=True),
    }
    record["power"] = power_rows(config)
    record["correlated"] = {
        f"{rho:.2f}": {
            **population_rates(config, corrected=True, rho=rho,
                               attendance=config.attendance),
            "day_check": day_level_rate(config, rho),
        }
        for rho in config.correlations
    }
    return record


def main(argv: list[str] | None = None) -> int:
    defaults = NullConfig()
    parser = argparse.ArgumentParser(prog="validation.aggregate_null")
    parser.add_argument("--reps", type=int, default=defaults.reps)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--out", default=None,
                        help="write the record to this JSON file")
    arguments = parser.parse_args(argv)
    record = run(NullConfig(reps=arguments.reps, seed=arguments.seed))
    text = json.dumps(record, indent=2, sort_keys=True)
    if arguments.out is not None:
        with open(arguments.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
