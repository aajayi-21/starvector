"""The V3 harness: does the score respond to quality? (spec P4 §11).

The harness scores holdout synthetic submissions at each degradation
level with the configured weights against the plain pool. The curve
of mean trial scores across levels **must be monotone** — a metric
that does not respond monotonically to submission quality is not
measuring quality (architecture section 23) — and the top level, pure
noise, must sit at the 0.5 baseline, which ties V3 to V2's claim.
"""

import argparse
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.canonical import JsonValue, canonical_json, sha256_hex
from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_tables)
from pipeline.config import (ConfigError, ScoringConfig, element_config,
                             fusion_weights, intake_gates, load_scoring_config,
                             outline_config, placement_config,
                             scoring_config_hash)
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import score_trial
from pool.artifacts import write_json_pretty, write_jsonl
from validation import harness
from validation.fitconfig import FitConfig, fit_config_hash, load_fit_config
from validation.generator import synthetic_set


@dataclass(frozen=True, slots=True)
class V3Level:
    level: int
    trial_count: int
    mean_p: float
    low: float
    high: float


def fit_harness_hash(name: str, scoring_hash: str, fit_hash: str) -> str:
    """One hash for each (harness, scoring config, fit config) triple."""
    return sha256_hex(canonical_json({
        "harness": name,
        "scoring_config_hash": scoring_hash,
        "fit_config_hash": fit_hash,
    }))


def bootstrap_interval(values: list[float], seed: int, count: int,
                       interval: float) -> tuple[float, float]:
    """A seeded bootstrap interval around the mean.

    count resamples at the stated interval level — the two come from
    the fit config (ruling 2026-08-10), thus the values that shape
    the gate verdict are hashed, not hardcoded.
    """
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=np.float64)
    means = np.sort([
        float(array[rng.integers(0, len(array), len(array))].mean())
        for _ in range(count)])
    tail = (1.0 - interval) / 2.0
    return (float(means[int(tail * count)]),
            float(means[min(count - 1, int((1.0 - tail) * count))]))


def monotone_verdict(levels: list[V3Level]) -> tuple[bool, bool]:
    """The two R4 checks: adjacent means in sequence, top near 0.5.

    The checks read the quantized values the record shows (ruling
    2026-08-10) — a verdict computed on digits the record rounds away
    can contradict the recorded numbers.
    """
    means = [harness.quantized(row.mean_p) for row in levels]
    ordered = all(means[i] > means[i + 1] for i in range(len(means) - 1))
    top = levels[-1]
    control_at_half = (harness.quantized(top.low) <= 0.5
                       <= harness.quantized(top.high))
    return ordered, control_at_half


def run_v3(config: ScoringConfig, fit_config: FitConfig, *,
           data_root: Path, records_root: Path,
           providers: Mapping[str, object] | None = None,
           clock: Callable[[], str] | None = None,
           code_version: str = "dev") -> dict[str, JsonValue]:
    """One full V3 run: level sets, trials, the monotone gate, record."""
    providers = providers or {}
    clock = clock or harness.default_clock

    loaded = load_pool_index(Path(config.input.preparation_record),
                             data_root, dev_only=config.report.dev_only)
    source = providers.get("sketch_pairs") or harness.wire_sketch_pairs(
        config, data_root)
    encoders = harness.wire_encoders(config, data_root, providers)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    harness.check_element_space(dict(loaded.record.provider_config_hashes),
                                slot_hashes)
    scoring_hash = scoring_config_hash(config, slot_hashes)
    fit_hash = fit_config_hash(fit_config)
    harness_hash = fit_harness_hash("v3", scoring_hash, fit_hash)
    generator_hash = harness.resolved_generator_hash(
        config, loaded.index, data_root, providers.get("generalizer"))
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], slot_hashes["sketch_pairs"],
        generator_hash)
    weights = fusion_weights(config)
    gates = intake_gates(config)
    placement = placement_config(config)

    # The stored table alone: the ~1,527-post build is a deliberate
    # owner step, not a harness side effect (spec P4 §17a item 7).
    table = harness.stored_table(loaded.index, fit_config, data_root,
                                 providers.get("generalizer"))

    def background() -> list[tuple[str, JsonValue]]:
        return harness.full_background(
            config, source, config.validation.submission_mode,
            loaded.index, placement, data_root,
            providers.get("generalizer"))

    relation_levels = any(row.relations > 0
                          for row in fit_config.generator.levels)
    required = ("element", "outline", "placement") if relation_levels \
        else ("element",)
    tables = ensure_commonness_tables(
        data_root=data_root, index=loaded.index,
        commonness_hash=commonness_hash, background=background,
        gates=gates, render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement,
        encoders=encoders, submission_mode=config.validation.submission_mode,
        clock=clock,
        required_channels=tuple(name for name in required
                                if name in weights))

    context = build_scoring_context(
        index=loaded.index, gates=gates, render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement, weights=weights, commonness=tables.tables,
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)

    level_rows: list[V3Level] = []
    trial_rows: list[dict[str, JsonValue]] = []
    for level_index in range(len(fit_config.generator.levels)):
        rows = synthetic_set(
            loaded.index, fit_config, table, placement,
            seed=fit_config.harness.v3_seed,
            count=fit_config.harness.v3_trials_for_each_level,
            level_index=level_index)
        harness.prewarm_records([row.record for row in rows], gates,
                                loaded.render, encoders)
        values = []
        for row in rows:
            trial = score_trial(row.record, row.image_id, context, encoders)
            values.append(trial.p)
            trial_rows.append({
                "key": row.key, "level": level_index,
                "p": harness.quantized(trial.p),
                "decoy_count": trial.decoy_count,
                "beaten": trial.beaten, "tied": trial.tied,
            })
        low, high = bootstrap_interval(
            values, fit_config.harness.v3_seed + level_index,
            fit_config.harness.v3_bootstrap_count,
            fit_config.harness.v3_interval)
        level_rows.append(V3Level(
            level=level_index, trial_count=len(values),
            mean_p=float(np.mean(values)), low=low, high=high))

    ordered, control_at_half = monotone_verdict(level_rows)
    aggregates: dict[str, JsonValue] = {
        "levels": [
            {"level": row.level, "trial_count": row.trial_count,
             "mean_p": harness.quantized(row.mean_p),
             "low": harness.quantized(row.low),
             "high": harness.quantized(row.high)}
            for row in level_rows
        ],
        "monotone": ordered,
        "control_at_half": control_at_half,
        "bootstrap_count": fit_config.harness.v3_bootstrap_count,
        "bootstrap_interval": fit_config.harness.v3_interval,
        # D13: how many background submissions each channel's
        # commonness mean ranges across — in the record, thus the
        # reviewer sees it at verdict time.
        "commonness_contributors": dict(tables.contributors),
    }

    directory = harness.validation_dir(data_root, "v3",
                                       loaded.index.index_id, harness_hash)
    write_jsonl(directory / "trials.jsonl", trial_rows)
    write_json_pretty(directory / "report.json", aggregates)
    meta: dict[str, JsonValue] = {
        "harness": "v3",
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "fit_config_hash": fit_hash,
        "commonness_config_hash": commonness_hash,
        "generator_config_hash": generator_hash,
        "created_at": clock(),
        "code_version": code_version,
    }
    write_json_pretty(directory / "meta.json", meta)

    content: dict[str, JsonValue] = {
        "harness": "v3",
        "tag": fit_config.tag,
        "dev_only": config.report.dev_only,
        **aggregates,
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "fit_config_hash": fit_hash,
        "commonness_config_hash": commonness_hash,
        "preparation_version_id": loaded.record.preparation_version_id,
        "fusion_weights": dict(config.fusion.weights),
        "fusion_weights_fitted": config.fusion.fit_record is not None,
        "fit_record": config.fusion.fit_record,
        "created_at": clock(),
        "code_version": code_version,
        **harness.VERDICT_TEMPLATE,
    }
    record_path = harness.write_harness_record(
        records_root, "v3", fit_config.tag, harness_hash, content)
    content["record_path"] = str(record_path)
    return content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.v3")
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
    content = run_v3(scoring, fit_config,
                     data_root=Path(arguments.data_root),
                     records_root=Path(arguments.records_root))
    if arguments.report:
        for row in content["levels"]:
            print(f"level {row['level']}: mean_p={row['mean_p']} "
                  f"[{row['low']}, {row['high']}] n={row['trial_count']}")
        print(f"monotone={content['monotone']} "
              f"control_at_half={content['control_at_half']}")
        print(f"record={content['record_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
