"""The V2c harness: what does stroke color do? (spec C1 section 6).

The V2 pairs and the V2 seeded targets. The harness scores each
pair sketch two ways — monochrome, and colorized through
validation.colorize — in one rgb context. The two sides must
agree with `Uniform(0, 1)`, and the score difference measures what
color does to the trial score. The harness refuses a "mono" context: that rule strips
colors and the gate measures nothing.
"""

import argparse
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.canonical import JsonValue
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
from validation.colorize import colorized_record
from validation.splits import select_keys
from validation.v2 import ks_significance, ks_statistic, target_for_trial


@dataclass(frozen=True, slots=True)
class V2cTrialRow:
    pair_key: str
    p_mono: float
    p_color: float
    decoy_count: int


@dataclass(frozen=True, slots=True)
class V2cReport:
    index_id: str
    harness_config_hash: str
    trial_count: int
    mono_statistic: float
    mono_significance: float
    color_statistic: float
    color_significance: float
    mean_delta_p: float
    mean_abs_delta_p: float
    max_abs_delta_p: float
    usage: tuple[tuple[str, tuple[int, int]], ...]
    record_path: str | None
    trials: tuple[V2cTrialRow, ...]


def run_v2c(config: ScoringConfig, *, data_root: Path, records_root: Path,
            providers: Mapping[str, object] | None = None,
            clock: Callable[[], str] | None = None,
            code_version: str = "dev") -> V2cReport:
    """One full V2c run: the V2 trials, plain and colorized."""
    providers = providers or {}
    clock = clock or harness.default_clock

    loaded = load_pool_index(Path(config.input.preparation_record),
                             data_root, dev_only=config.report.dev_only)
    if loaded.render.stroke_color != "rgb":
        raise ValueError(
            'v2c needs an rgb render - the "mono" rule strips colors and '
            "the gate measures nothing (spec C1 section 6). Point the "
            "scoring config at a preparation with "
            'linedraw.stroke_color "rgb"')

    mode = config.validation.submission_mode
    source = providers.get("sketch_pairs") or harness.wire_sketch_pairs(
        config, data_root)
    keys = harness.pair_keys_of(source)
    fractions = config.commonness.split_fractions
    salt = config.commonness.split_salt
    synthetic = config.commonness.synthetic
    dataset_count = config.commonness.background_count \
        - (synthetic.count if synthetic else 0)
    v2_keys = select_keys(keys, salt, fractions, "v2",
                          config.validation.v2_trial_count)
    background_keys = select_keys(keys, salt, fractions, "background",
                                  dataset_count)
    pairs = harness.pairs_by_key(source, set(v2_keys) | set(background_keys))
    harness.check_selected_pairs(pairs, v2_keys + background_keys,
                                 intake_gates(config),
                                 loaded.render.canvas_px, mode)

    encoders = harness.wire_encoders(config, data_root, providers)
    sketch_delta = harness.UsageDelta(encoders.sketch)
    text_delta = harness.UsageDelta(encoders.text)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    harness.check_element_space(dict(loaded.record.provider_config_hashes),
                                slot_hashes)
    dataset_hash = slot_hashes["sketch_pairs"]
    scoring_hash = scoring_config_hash(config, slot_hashes)
    harness_hash = harness.harness_config_hash("v2c", scoring_hash)
    generator_hash = harness.resolved_generator_hash(
        config, loaded.index, data_root, providers.get("generalizer"))
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], dataset_hash, generator_hash)
    weights = fusion_weights(config)

    def background_records() -> list[tuple[str, JsonValue]]:
        rows = [(key, harness.submission_record(pairs[key], mode))
                for key in background_keys]
        rows.extend(harness.synthetic_background(
            config, loaded.index, placement_config(config), data_root,
            providers.get("generalizer")))
        rows.sort(key=lambda entry: entry[0])
        return rows

    tables = ensure_commonness_tables(
        data_root=data_root, index=loaded.index,
        commonness_hash=commonness_hash, background=background_records,
        gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement_config(config), encoders=encoders,
        submission_mode=mode, clock=clock)

    context = build_scoring_context(
        index=loaded.index, gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement_config(config),
        weights=weights, commonness=tables.tables,
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)

    seed = config.validation.v2_target_seed
    mono_records = {key: harness.submission_record(pairs[key], mode)
                    for key in v2_keys}
    color_records = {key: colorized_record(mono_records[key], seed, key)
                     for key in v2_keys}
    harness.prewarm_records(
        list(mono_records.values()) + list(color_records.values()),
        intake_gates(config), loaded.render, encoders)
    trials: list[V2cTrialRow] = []
    for trial_index, key in enumerate(v2_keys):
        target = target_for_trial(loaded.index.image_ids, seed, trial_index)
        mono = score_trial(mono_records[key], target, context, encoders)
        color = score_trial(color_records[key], target, context, encoders)
        trials.append(V2cTrialRow(
            pair_key=key, p_mono=mono.p, p_color=color.p,
            decoy_count=mono.decoy_count))

    count = len(trials)
    mono_statistic = ks_statistic([row.p_mono for row in trials])
    color_statistic = ks_statistic([row.p_color for row in trials])
    deltas = np.asarray([row.p_color - row.p_mono for row in trials],
                        dtype=np.float64)                  # (count,)
    usage = (
        ("sketch_encoder", (sketch_delta.posts, sketch_delta.cache_hits)),
        ("text_encoder", (text_delta.posts, text_delta.cache_hits)),
    )

    directory = harness.validation_dir(data_root, "v2c",
                                       loaded.index.index_id, harness_hash)
    write_jsonl(directory / "trials.jsonl", [
        {"pair_key": row.pair_key,
         "p_mono": harness.quantized(row.p_mono),
         "p_color": harness.quantized(row.p_color),
         "decoy_count": row.decoy_count}
        for row in trials])
    aggregates: dict[str, JsonValue] = {
        "trial_count": count,
        "mono_ks_statistic": harness.quantized(mono_statistic),
        "mono_ks_significance": harness.quantized(
            ks_significance(mono_statistic, count)),
        "color_ks_statistic": harness.quantized(color_statistic),
        "color_ks_significance": harness.quantized(
            ks_significance(color_statistic, count)),
        "mean_delta_p": harness.quantized(float(deltas.mean())),
        "mean_abs_delta_p": harness.quantized(float(np.abs(deltas).mean())),
        "max_abs_delta_p": harness.quantized(float(np.abs(deltas).max())),
    }
    write_json_pretty(directory / "report.json", aggregates)
    meta: dict[str, JsonValue] = {
        "harness": "v2c",
        "submission_mode": mode,
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "commonness_config_hash": commonness_hash,
        "dataset_config_hash": dataset_hash,
        "preparation_version_id": loaded.record.preparation_version_id,
        "provider_usage": {slot: {"posts": posts, "cache_hits": hits}
                           for slot, (posts, hits) in usage},
        "created_at": clock(),
        "code_version": code_version,
    }
    write_json_pretty(directory / "meta.json", meta)

    record_path = None
    if count == config.validation.v2_trial_count:
        content: dict[str, JsonValue] = {
            "harness": "v2c",
            "tag": config.validation.tag,
            "dev_only": config.report.dev_only,
            **aggregates,
            "index_id": loaded.index.index_id,
            "harness_config_hash": harness_hash,
            "scoring_config_hash": scoring_hash,
            "commonness_config_hash": commonness_hash,
            "dataset_config_hash": dataset_hash,
            "preparation_version_id": loaded.record.preparation_version_id,
            "provider_usage": {slot: {"posts": posts, "cache_hits": hits}
                               for slot, (posts, hits) in usage},
            "fusion_weights": dict(config.fusion.weights),
            "fusion_weights_fitted": config.fusion.fit_record is not None,
            "fit_record": config.fusion.fit_record,
            "created_at": clock(),
            "code_version": code_version,
            **harness.VERDICT_TEMPLATE,
        }
        record_path = str(harness.write_harness_record(
            records_root, "v2c", config.validation.tag, harness_hash,
            content))

    return V2cReport(
        index_id=loaded.index.index_id, harness_config_hash=harness_hash,
        trial_count=count,
        mono_statistic=mono_statistic,
        mono_significance=ks_significance(mono_statistic, count),
        color_statistic=color_statistic,
        color_significance=ks_significance(color_statistic, count),
        mean_delta_p=float(deltas.mean()),
        mean_abs_delta_p=float(np.abs(deltas).mean()),
        max_abs_delta_p=float(np.abs(deltas).max()),
        usage=usage, record_path=record_path, trials=tuple(trials))


def format_report(report: V2cReport) -> str:
    """The numbers, one for each line (CLAUDE.md section 11)."""
    lines = [
        f"v2c {report.index_id[:8]}  harness "
        f"c{report.harness_config_hash[:8]}",
        f"trials={report.trial_count}",
        f"mono: ks={report.mono_statistic:.4f} "
        f"significance={report.mono_significance:.4f}",
        f"color: ks={report.color_statistic:.4f} "
        f"significance={report.color_significance:.4f}",
        f"delta_p: mean={report.mean_delta_p:+.4f} "
        f"mean_abs={report.mean_abs_delta_p:.4f} "
        f"max_abs={report.max_abs_delta_p:.4f}",
    ]
    for slot, (posts, hits) in report.usage:
        lines.append(f"{slot}: posts={posts} cache_hits={hits}")
    if report.record_path:
        lines.append(f"record={report.record_path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.v2c")
    parser.add_argument("--config", required=True)
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--records-root", default="validation/records")
    parser.add_argument("--report", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        config = load_scoring_config(Path(arguments.config))
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    report = run_v2c(config, data_root=Path(arguments.data_root),
                     records_root=Path(arguments.records_root))
    if arguments.report:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
