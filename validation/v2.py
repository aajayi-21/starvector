"""The V2 harness: is the baseline correct? (spec P2 section 13).

Human sketches paired with seeded random targets — the no-information
condition. The full path runs, correction included, and the trial
scores must agree with `Uniform(0, 1)`, tested with the two-sided
Kolmogorov-Smirnov statistic. A failure is a Rule 3 audit, not a
tuning task.
"""

import argparse
import math
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from core.canonical import JsonValue, sha256_hex
from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_table)
from pipeline.config import (ConfigError, ScoringConfig, fusion_weights,
                             intake_gates, load_scoring_config,
                             outline_config, scoring_config_hash)
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import score_trial
from pool.artifacts import write_json_pretty, write_jsonl
from providers.protocols import SketchPair
from validation import harness
from validation.splits import select_keys

# The Kolmogorov series cap. Terms shrink as exp(-2 k^2 lambda^2) and
# vanish far before this cap for each usable statistic.
_KOLMOGOROV_TERMS = 100


@dataclass(frozen=True, slots=True)
class V2TrialRow:
    pair_key: str
    p: float
    decoy_count: int
    beaten: int
    tied: int


@dataclass(frozen=True, slots=True)
class V2Report:
    index_id: str
    harness_config_hash: str
    trial_count: int
    statistic: float
    significance: float
    decoy_count_min: int
    decoy_count_max: int
    usage: tuple[tuple[str, tuple[int, int]], ...]
    dataset_bytes_retrieved: int
    record_path: str | None
    trials: tuple[V2TrialRow, ...]


def ks_statistic(scores: list[float]) -> float:
    """The two-sided Kolmogorov-Smirnov statistic against `Uniform(0, 1)`.

    D = max across sorted values u_(i) of max(i/n - u_(i),
    u_(i) - (i-1)/n). Pure and deterministic (D11).
    """
    if not scores:
        raise ValueError("no scores")
    ordered = np.sort(np.asarray(scores, dtype=np.float64))   # (n,)
    count = ordered.shape[0]
    positions = np.arange(1, count + 1, dtype=np.float64)     # (n,)
    above = positions / count - ordered
    below = ordered - (positions - 1.0) / count
    return float(np.maximum(above, below).max())


def ks_significance(statistic: float, count: int) -> float:
    """The asymptotic significance value of the statistic.

    Q(lambda) = 2 * sum for k >= 1 of (-1)^(k-1) exp(-2 k^2 lambda^2)
    at lambda = sqrt(n) * D — Kolmogorov (1933), Smirnov (1948).
    Clamped to [0, 1]. Pure code, no dependency (D11).
    """
    if count < 1:
        raise ValueError("count must be positive")
    lam = math.sqrt(count) * statistic
    if lam == 0.0:
        return 1.0
    total = 0.0
    for k in range(1, _KOLMOGOROV_TERMS + 1):
        total += (-1.0) ** (k - 1) * math.exp(-2.0 * k * k * lam * lam)
    return min(1.0, max(0.0, 2.0 * total))


def target_for_trial(image_ids: tuple[str, ...], seed: int,
                     trial_index: int) -> str:
    """The seeded target of one trial: a pure function (spec section 17).

    The modulo bias is below N / 2**64 and is commented as accepted.
    """
    value = int(sha256_hex(f"v2-target:{seed}:{trial_index}")[:16], 16)
    return image_ids[value % len(image_ids)]


def run_v2(config: ScoringConfig, *, data_root: Path, records_root: Path,
           providers: Mapping[str, object] | None = None,
           clock: Callable[[], str] | None = None,
           code_version: str = "dev") -> V2Report:
    """One full V2 run: plain index, commonness, trials, KS, record."""
    providers = providers or {}
    clock = clock or harness.default_clock

    loaded = load_pool_index(Path(config.input.preparation_record),
                             data_root, dev_only=config.report.dev_only)

    source = providers.get("sketch_pairs") or harness.wire_sketch_pairs(
        config, data_root)
    keys = harness.pair_keys_of(source)
    fractions = config.commonness.split_fractions
    salt = config.commonness.split_salt
    v2_keys = select_keys(keys, salt, fractions, "v2",
                          config.validation.v2_trial_count)
    background_keys = select_keys(keys, salt, fractions, "background",
                                  config.commonness.background_count)
    pairs = harness.pairs_by_key(source, set(v2_keys) | set(background_keys))
    # Pre-flight before the encoder spend: each selected sketch (trial
    # and background) must clear the Layer 0 gates.
    harness.check_selected_pairs(pairs, v2_keys + background_keys,
                                 intake_gates(config),
                                 loaded.render.canvas_px)

    sketch_encoder = providers.get("sketch_encoder") \
        or harness.wire_sketch_encoder(config, data_root)
    sketch_delta = harness.UsageDelta(sketch_encoder)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    dataset_hash = slot_hashes["sketch_pairs"]
    scoring_hash = scoring_config_hash(config, slot_hashes)
    harness_hash = harness.harness_config_hash("v2", scoring_hash)
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"], dataset_hash)

    def background_pairs() -> list[SketchPair]:
        rows = [pairs[key] for key in background_keys]
        rows.sort(key=lambda pair: pair.pair_key)
        return rows

    table = ensure_commonness_table(
        data_root=data_root, index=loaded.index,
        commonness_hash=commonness_hash, background=background_pairs,
        render=loaded.render, outline=outline_config(config),
        encoder=sketch_encoder, clock=clock)

    context = build_scoring_context(
        index=loaded.index, gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), weights=fusion_weights(config),
        commonness={"outline": table.table},
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)

    trials: list[V2TrialRow] = []
    for trial_index, key in enumerate(v2_keys):
        pair = pairs[key]
        record = harness.submission_record_from_strokes(pair.sketch_strokes)
        target = target_for_trial(loaded.index.image_ids,
                                  config.validation.v2_target_seed,
                                  trial_index)
        trial = score_trial(record, target, context, sketch_encoder)
        trials.append(V2TrialRow(
            pair_key=key, p=trial.p, decoy_count=trial.decoy_count,
            beaten=trial.beaten, tied=trial.tied))

    count = len(trials)
    statistic = ks_statistic([row.p for row in trials])
    significance = ks_significance(statistic, count)
    decoy_counts = [row.decoy_count for row in trials]
    usage = (
        ("sketch_encoder", (sketch_delta.posts, sketch_delta.cache_hits)),
    )

    directory = harness.validation_dir(data_root, "v2",
                                       loaded.index.index_id, harness_hash)
    write_jsonl(directory / "trials.jsonl", [
        {"pair_key": row.pair_key, "p": harness.quantized(row.p),
         "decoy_count": row.decoy_count, "beaten": row.beaten,
         "tied": row.tied}
        for row in trials])
    aggregates: dict[str, JsonValue] = {
        "trial_count": count,
        "ks_statistic": harness.quantized(statistic),
        "ks_significance": harness.quantized(significance),
        "decoy_count_min": min(decoy_counts),
        "decoy_count_max": max(decoy_counts),
    }
    write_json_pretty(directory / "report.json", aggregates)
    meta: dict[str, JsonValue] = {
        "harness": "v2",
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "commonness_config_hash": commonness_hash,
        "dataset_config_hash": dataset_hash,
        "preparation_version_id": loaded.record.preparation_version_id,
        "provider_usage": {slot: {"posts": posts, "cache_hits": hits}
                           for slot, (posts, hits) in usage},
        "dataset_bytes_retrieved": int(source.bytes_retrieved),
        "created_at": clock(),
        "code_version": code_version,
    }
    write_json_pretty(directory / "meta.json", meta)

    record_path = None
    if count == config.validation.v2_trial_count:
        content: dict[str, JsonValue] = {
            "harness": "v2",
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
            "dataset_bytes_retrieved": int(source.bytes_retrieved),
            "created_at": clock(),
            "code_version": code_version,
            **harness.VERDICT_TEMPLATE,
        }
        record_path = str(harness.write_harness_record(
            records_root, "v2", config.validation.tag, harness_hash, content))

    return V2Report(
        index_id=loaded.index.index_id, harness_config_hash=harness_hash,
        trial_count=count, statistic=statistic, significance=significance,
        decoy_count_min=min(decoy_counts),
        decoy_count_max=max(decoy_counts), usage=usage,
        dataset_bytes_retrieved=int(source.bytes_retrieved),
        record_path=record_path, trials=tuple(trials))


def format_report(report: V2Report) -> str:
    """The numbers, one for each line (CLAUDE.md section 11)."""
    lines = [
        f"v2 {report.index_id[:8]}  harness c{report.harness_config_hash[:8]}",
        f"trials={report.trial_count}",
        f"ks_statistic={report.statistic:.4f}",
        f"ks_significance={report.significance:.4f}",
        f"decoy_count=[{report.decoy_count_min}, {report.decoy_count_max}]",
    ]
    for slot, (posts, hits) in report.usage:
        lines.append(f"{slot}: posts={posts} cache_hits={hits}")
    lines.append(f"dataset_bytes_retrieved={report.dataset_bytes_retrieved}")
    if report.record_path:
        lines.append(f"record={report.record_path}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.v2")
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
    report = run_v2(config, data_root=Path(arguments.data_root),
                    records_root=Path(arguments.records_root))
    if arguments.report:
        print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
