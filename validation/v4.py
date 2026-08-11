"""The V4 harness: does each channel earn its position? (spec P4 §11).

For each channel in the candidate set: fit the remaining weights
again on the fit split without it, and report the holdout change. A
channel with no measurable cost on removal is cut (architecture
section 23). The report also carries the second half of the placement
cut criterion (D8): the ablation cost against the ruled line.
"""

import argparse
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from core.canonical import JsonValue
from pipeline.config import ConfigError, ScoringConfig, load_scoring_config
from pool.artifacts import write_json_pretty
from validation import harness
from validation.fit import (FitData, collect_fit_data, fit_objective,
                            grid_line, grid_simplex, readable_counts)
from validation.fitconfig import FitConfig, load_fit_config
from validation.v3 import fit_harness_hash


def _grid_for(channels: tuple[str, ...],
              fit_config: FitConfig) -> list[dict[str, float]]:
    """The grid across one channel subset.

    One channel: the single weight. Two: the line between them.
    Three: the simplex. The subset comes from an ablation, thus the
    names change — the line generalizes across a pair.
    """
    names = sorted(channels)
    if len(names) == 1:
        return [{names[0]: 1.0}]
    if len(names) == 2:
        points = fit_config.fit.line_points
        return [{names[0]: position / (points - 1),
                 names[1]: 1.0 - position / (points - 1)}
                for position in range(points)]
    return grid_simplex(fit_config.fit.simplex_step)


def _best(grid: list[dict[str, float]],
          objective: Callable[[Mapping[str, float]], float],
          ) -> tuple[dict[str, float], float]:
    """The first grid point with the highest quantized objective.

    The quantized compare matches the fit's _winner rule (ruling
    2026-08-10) — two selectors on one objective must pick one point.
    """
    best_weights = grid[0]
    best_value = harness.quantized(objective(grid[0]))
    for weights in grid[1:]:
        value = harness.quantized(objective(weights))
        if value > best_value:
            best_weights, best_value = weights, value
    return best_weights, best_value


def run_v4(config: ScoringConfig, fit_config: FitConfig, *,
           data_root: Path, records_root: Path,
           providers: Mapping[str, object] | None = None,
           clock: Callable[[], str] | None = None,
           code_version: str = "dev") -> dict[str, JsonValue]:
    """One full V4 run: the ablation table and its record."""
    clock = clock or harness.default_clock
    data = collect_fit_data(config, fit_config, data_root=data_root,
                            providers=providers, clock=clock)
    # One basis across the full table (ruling 2026-08-10): each
    # ablation cost subtracts two objectives measured across the same
    # trials, thus the cost reads the channel and not a data switch.
    basis = "mixed" if data.placement_alive else "source1"
    objective = fit_objective(data, "fit", basis)
    holdout = fit_objective(data, "holdout", basis)
    counts = readable_counts(data, "holdout", basis)

    full_set = ("outline", "element", "placement") if data.placement_alive \
        else ("outline", "element")
    full_weights, _ = _best(_grid_for(full_set, fit_config), objective)
    full_holdout = holdout(full_weights)

    ablations: list[dict[str, JsonValue]] = []
    for name in full_set:
        remaining = tuple(other for other in full_set if other != name)
        weights, _ = _best(_grid_for(remaining, fit_config), objective)
        value = holdout(weights)
        ablations.append({
            "removed": name,
            "refit_weights": weights,
            "holdout_objective": harness.quantized(value),
            "cost": harness.quantized(full_holdout - value),
            "readable_trials": counts(weights),
        })

    placement_cost = next(
        (row["cost"] for row in ablations if row["removed"] == "placement"),
        None)
    placement_earns = placement_cost is not None \
        and placement_cost >= fit_config.fit.ablation_line

    harness_hash = fit_harness_hash("v4", data.scoring_hash, data.fit_hash)
    aggregates: dict[str, JsonValue] = {
        "channel_set": list(full_set),
        "objective_basis": basis,
        "full_weights": full_weights,
        "full_holdout_objective": harness.quantized(full_holdout),
        "ablations": ablations,
        "placement_alive": data.placement_alive,
        "placement_signal": (None if data.placement_signal is None
                             else harness.quantized(data.placement_signal)),
        "placement_ablation_line": fit_config.fit.ablation_line,
        "placement_earns_its_place": placement_earns,
        "commonness_contributors": {
            "union": dict(data.union_contributors),
            "pool": dict(data.pool_contributors)},
    }
    directory = harness.validation_dir(data_root, "v4",
                                       data.pool_index.index_id,
                                       harness_hash)
    write_json_pretty(directory / "report.json", aggregates)
    meta: dict[str, JsonValue] = {
        "harness": "v4",
        "index_id": data.pool_index.index_id,
        "union_index_id": data.union_index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": data.scoring_hash,
        "fit_config_hash": data.fit_hash,
        "created_at": clock(),
        "code_version": code_version,
    }
    write_json_pretty(directory / "meta.json", meta)

    content: dict[str, JsonValue] = {
        "harness": "v4",
        "tag": fit_config.tag,
        "dev_only": config.report.dev_only,
        **aggregates,
        "index_id": data.pool_index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": data.scoring_hash,
        "fit_config_hash": data.fit_hash,
        "preparation_version_id": data.preparation_version_id,
        "created_at": clock(),
        "code_version": code_version,
        **harness.VERDICT_TEMPLATE,
    }
    record_path = harness.write_harness_record(
        records_root, "v4", fit_config.tag, harness_hash, content)
    content["record_path"] = str(record_path)
    return content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.v4")
    parser.add_argument("--config", required=True, help="the fit config")
    parser.add_argument("--scoring-config", required=True)
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--records-root", default="validation/records")
    parser.add_argument("--report", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        fit_config = load_fit_config(Path(arguments.config))
        scoring = load_scoring_config(Path(arguments.scoring_config))
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    content = run_v4(scoring, fit_config,
                     data_root=Path(arguments.data_root),
                     records_root=Path(arguments.records_root))
    if arguments.report:
        print(f"full: weights={content['full_weights']} "
              f"holdout={content['full_holdout_objective']}")
        for row in content["ablations"]:
            print(f"without {row['removed']}: "
                  f"holdout={row['holdout_objective']} cost={row['cost']}")
        print(f"placement_earns_its_place="
              f"{content['placement_earns_its_place']}")
        print(f"record={content['record_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
