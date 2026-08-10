"""The V5 harness: is commonness correction working? (spec P4 §11).

Two instruments. The concentration count: across the background set,
how frequently each pool image lands in a fused top ten — a heavy tail
means the correction is too weak (architecture section 23). The
slope: across seeded no-information trials, the rank correlation
between the target's commonness and its trial score, for each channel
— the standing Phase 3 measurement (+0.4722 outline, +0.2053
element), reported here before and after the source B background so
the D11 criterion has its numbers.
"""

import argparse
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np

from core.canonical import JsonValue
from core.fusion import active_channels, fuse
from core.intake import validate_submission
from core.normalize import commonness_correct, standardize
from core.types import ROUTING_TABLE, ChannelName, PoolScores
from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_tables)
from pipeline.config import (ConfigError, ScoringConfig, element_config,
                             fusion_weights, intake_gates, load_scoring_config,
                             outline_config, placement_config,
                             scoring_config_hash)
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import channel_scores, encode_submission, score_trial
from pool.artifacts import write_json_pretty
from validation import harness
from validation.fitconfig import FitConfig, fit_config_hash, load_fit_config
from validation.v2 import target_for_trial
from validation.v3 import fit_harness_hash

# The concentration tail line: images above this multiple of the
# equal-share expectation are counted (D9).
_TAIL_MULTIPLE = 3.0


def spearman(first: list[float], second: list[float]) -> float:
    """The rank correlation, with mean ranks on equal values."""
    def ranks(values: list[float]) -> np.ndarray:
        array = np.asarray(values, dtype=np.float64)
        order = np.argsort(array, kind="stable")
        result = np.empty(len(values), dtype=np.float64)
        position = 0
        while position < len(values):
            end = position
            while (end + 1 < len(values)
                   and array[order[end + 1]] == array[order[position]]):
                end += 1
            mean_rank = (position + end) / 2.0 + 1.0
            for index in range(position, end + 1):
                result[order[index]] = mean_rank
            position = end + 1
        return result

    a, b = ranks(first), ranks(second)
    a -= a.mean()
    b -= b.mean()
    scale = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if scale == 0.0:
        raise ValueError("a constant sequence has no rank correlation")
    return float((a * b).sum() / scale)


def run_v5(config: ScoringConfig, fit_config: FitConfig, *,
           data_root: Path, records_root: Path,
           providers: Mapping[str, object] | None = None,
           clock: Callable[[], str] | None = None,
           code_version: str = "dev") -> dict[str, JsonValue]:
    """One full V5 run: concentration, slopes, record."""
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
    harness_hash = fit_harness_hash("v5", scoring_hash, fit_hash)
    generator_hash = harness.resolved_generator_hash(
        config, loaded.index, data_root, providers.get("generalizer"))
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], slot_hashes["sketch_pairs"],
        generator_hash)
    weights = fusion_weights(config)
    gates = intake_gates(config)
    placement = placement_config(config)

    def background() -> list[tuple[str, JsonValue]]:
        return harness.full_background(
            config, source, config.validation.submission_mode,
            loaded.index, placement, data_root,
            providers.get("generalizer"))

    background_rows = background()
    tables = ensure_commonness_tables(
        data_root=data_root, index=loaded.index,
        commonness_hash=commonness_hash,
        background=lambda: background_rows,
        gates=gates, render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement, channels=tuple(sorted(weights)),
        encoders=encoders, submission_mode=config.validation.submission_mode,
        clock=clock)

    context = build_scoring_context(
        index=loaded.index, gates=gates, render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement, weights=weights, commonness=tables.tables,
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)

    # Concentration: each background submission's fused top ten.
    count = len(loaded.index.image_ids)
    appearances = np.zeros(count, dtype=np.int64)
    harness.prewarm_records([record for _, record in background_rows],
                            gates, loaded.render, encoders)
    scored = 0
    for _, record in background_rows:
        submission = validate_submission(record, gates,
                                         loaded.render.canvas_px)
        encoded = encode_submission(submission, loaded.render, encoders)
        standardized: dict[ChannelName, PoolScores] = {}
        for name in sorted(active_channels(encoded, ROUTING_TABLE)):
            if name not in tables.tables:
                continue
            raw = channel_scores(name, encoded, loaded.index,
                                 outline_config(config),
                                 element_config(config), placement)
            standardized[name] = standardize(
                commonness_correct(raw, tables.tables[name]))
        if not standardized:
            continue
        fused = fuse(standardized,
                     {name: weights[name] for name in standardized})
        top = np.argsort(-fused, kind="stable")[:10]
        appearances[top] += 1
        scored += 1

    expectation = 10.0 * scored / count
    tail = int((appearances > _TAIL_MULTIPLE * expectation).sum())
    histogram: dict[str, int] = {}
    for value in appearances.tolist():
        histogram[str(value)] = histogram.get(str(value), 0) + 1

    # The slope: seeded no-information trials, mode-built records, and
    # for each channel with a table the rank correlation between the
    # target's commonness and p.
    keys = harness.pair_keys_of(source)
    from validation.splits import select_keys

    trial_keys = select_keys(keys, config.commonness.split_salt,
                             config.commonness.split_fractions, "v2",
                             config.validation.v2_trial_count)
    pairs = harness.pairs_by_key(source, set(trial_keys))
    mode = config.validation.submission_mode
    harness.check_selected_pairs(pairs, trial_keys, gates,
                                 loaded.render.canvas_px, mode)
    records = {key: harness.submission_record(pairs[key], mode)
               for key in trial_keys}
    harness.prewarm_records(list(records.values()), gates, loaded.render,
                            encoders)
    position_of = {image_id: position for position, image_id
                   in enumerate(loaded.index.image_ids)}
    scores: list[float] = []
    targets: list[int] = []
    for trial_index, key in enumerate(trial_keys):
        target = target_for_trial(loaded.index.image_ids,
                                  config.validation.v2_target_seed,
                                  trial_index)
        trial = score_trial(records[key], target, context, encoders)
        scores.append(trial.p)
        targets.append(position_of[target])

    slopes: dict[str, JsonValue] = {}
    for name, table in sorted(tables.tables.items()):
        values = [float(table[position]) for position in targets]
        slopes[name] = harness.quantized(spearman(values, scores))

    aggregates: dict[str, JsonValue] = {
        "background_count": len(background_rows),
        "background_scored": scored,
        "appearance_histogram": histogram,
        "equal_share_expectation": harness.quantized(expectation),
        "tail_multiple": _TAIL_MULTIPLE,
        "images_above_tail_line": tail,
        "slope_trial_count": len(scores),
        "commonness_slopes": slopes,
        "phase3_reference_slopes": {"outline": 0.4722, "element": 0.2053},
    }
    directory = harness.validation_dir(data_root, "v5",
                                       loaded.index.index_id, harness_hash)
    write_json_pretty(directory / "report.json", aggregates)
    meta: dict[str, JsonValue] = {
        "harness": "v5",
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "fit_config_hash": fit_hash,
        "commonness_config_hash": commonness_hash,
        "created_at": clock(),
        "code_version": code_version,
    }
    write_json_pretty(directory / "meta.json", meta)

    content: dict[str, JsonValue] = {
        "harness": "v5",
        "tag": fit_config.tag,
        "dev_only": config.report.dev_only,
        **aggregates,
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "fit_config_hash": fit_hash,
        "commonness_config_hash": commonness_hash,
        "preparation_version_id": loaded.record.preparation_version_id,
        "created_at": clock(),
        "code_version": code_version,
        **harness.VERDICT_TEMPLATE,
    }
    record_path = harness.write_harness_record(
        records_root, "v5", fit_config.tag, harness_hash, content)
    content["record_path"] = str(record_path)
    return content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.v5")
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
    content = run_v5(scoring, fit_config,
                     data_root=Path(arguments.data_root),
                     records_root=Path(arguments.records_root))
    if arguments.report:
        print(f"images above {content['tail_multiple']}x expectation: "
              f"{content['images_above_tail_line']}")
        print(f"slopes={content['commonness_slopes']} "
              f"(phase 3: {content['phase3_reference_slopes']})")
        print(f"record={content['record_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
