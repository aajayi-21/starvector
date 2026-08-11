"""Weight fitting on labeled pairs (spec P4 section 10, §19).

The one permitted fit: labeled pairs where correspondence is there by
construction — dataset pairs (source 1, against the union index) and
synthetic submissions (source 2, against the plain pool). A grid, no
optimizer. The full curve goes into a committed fit record with
verdict fields, and the weights freeze only when the owner approves
(R3).

I6 boundary (R1): this module and the generator import datasets,
generators, and the pipeline — and nothing that stores or serves live
player submissions. The fit-boundary scan test pins the import set.
"""

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from core.canonical import JsonValue, sha256_hex
from core.fusion import active_channels, fuse
from core.intake import validate_submission
from core.ranking import decoy_set, rank
from core.types import (ROUTING_TABLE, ChannelName, PoolIndex, PoolScores,
                        ScoringContext, TrialScore)
from core.normalize import commonness_correct, standardize
from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_tables)
from pipeline.config import (ConfigError, ScoringConfig, element_config,
                             fusion_weights, intake_gates, load_scoring_config,
                             outline_config, placement_config,
                             scoring_config_hash)
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import Encoders, channel_scores, encode_submission
from pool.artifacts import write_json_pretty
from pool.preparation.config import load_preparation_config
from pool.preparation.run import wire_slot
from validation import harness
from validation.fitconfig import FitConfig, fit_config_hash, load_fit_config
from validation.generalize import table_hash, vocabulary_digest
from validation.generator import generator_config_hash, synthetic_set
from validation.splits import selection_key, split_of
from validation.v1 import _check_shared_space, build_union_index


@dataclass(frozen=True, slots=True)
class LabeledTrial:
    """One labeled pair, reduced to what the grid reads.

    standardized holds the channel-level standardized score vectors of
    this submission — the Layer 5 output. The grid then fuses subsets
    of them with candidate weights and ranks. The channel set can be
    different between trials (a level 3 synthetic has no relations), and
    the fusion denominator handles that, as always (I5).

    level is the degradation level of a synthetic trial and None for
    a dataset pair — the D8 strong-trial filter reads it from the
    trial itself, thus no positional pairing can drift.
    """

    key: str
    standardized: Mapping[ChannelName, PoolScores]
    label: str
    level: int | None = None


def standardized_scores(record: JsonValue, context: ScoringContext,
                        encoders: Encoders,
                        ) -> dict[ChannelName, PoolScores]:
    """The Layer 0 through Layer 5 prefix of score_trial.

    The fit computes this one time for each pair and then fuses with
    each grid point — a channel computation at each grid point
    multiplies the work by the grid dimension with no change in the
    numbers.
    """
    submission = validate_submission(record, context.gates,
                                     context.render.canvas_px)
    encoded = encode_submission(submission, context.render, encoders)
    standardized: dict[ChannelName, PoolScores] = {}
    for name in sorted(active_channels(encoded, ROUTING_TABLE)):
        raw = channel_scores(name, encoded, context.index, context.outline,
                             context.element, context.placement)
        if name not in context.commonness:
            raise ValueError(f"channel {name!r} has no commonness table")
        standardized[name] = standardize(
            commonness_correct(raw, context.commonness[name]))
    return standardized


def trial_with_weights(trial: LabeledTrial, weights: Mapping[str, float],
                       index: PoolIndex) -> TrialScore:
    """Rank one labeled trial with one candidate weight table.

    The candidate names the channels it reads: a channel with weight
    zero is dropped from the fused set here, in memory — a committed
    config cannot hold a zero weight, and an endpoint winner thus
    means a channel cut, not a freeze (spec P4 section 10.2).
    """
    scores = {name: trial.standardized[name]
              for name, weight in weights.items()
              if weight > 0.0 and name in trial.standardized}
    fused = fuse(scores, {name: weight for name, weight in weights.items()
                          if weight > 0.0})
    decoys = decoy_set(index, trial.label)
    return rank(fused, trial.label, decoys, index)


def readable_trial(trial: LabeledTrial,
                   weights: Mapping[str, float]) -> bool:
    """The check that a positive-weight channel is active in this trial."""
    return any(weight > 0.0 and name in trial.standardized
               for name, weight in weights.items())


def mean_trial_score(trials: Sequence[LabeledTrial],
                     weights: Mapping[str, float],
                     index: PoolIndex) -> float:
    """The fitting objective of §19: the mean across labeled pairs.

    A trial with no channel the candidate reads counts 0.5 — with
    no information the trial score falls at each point of [0, 1]
    with equal probability, thus 0.5 is the one honest mean — and a
    fixed trial set keeps grid points comparable (ruling
    2026-08-10). The curve rows hold the readable counts, thus a
    point that gets 0.5 for part of its data shows in the record.
    """
    total = 0.0
    for trial in trials:
        if not readable_trial(trial, weights):
            total += 0.5
            continue
        total += trial_with_weights(trial, weights, index).p
    return total / len(trials)


def grid_line(points: int) -> list[dict[str, float]]:
    """The two-channel grid: alpha across [0, 1] (D6)."""
    return [{"element": position / (points - 1),
             "outline": 1.0 - position / (points - 1)}
            for position in range(points)]


def grid_simplex(step: float) -> list[dict[str, float]]:
    """The three-channel grid on the weight simplex (D6)."""
    steps = round(1.0 / step)
    table = []
    for a in range(steps + 1):
        for b in range(steps + 1 - a):
            table.append({
                "element": a / steps,
                "outline": b / steps,
                "placement": (steps - a - b) / steps,
            })
    return table


def fit_split_keys(pair_keys: list[str], scoring: ScoringConfig,
                   fit_config: FitConfig) -> tuple[list[str], list[str]]:
    """The source 1 fit and holdout keys (D5).

    The tail of the v1 split — its members after the first
    v1_pair_count in selection sequence, which are the recorded gate
    pairs — ordered again by the fit salt and cut into the two splits.
    Disjoint from the gates and from each other by construction.
    """
    fractions = scoring.commonness.split_fractions
    salt = scoring.commonness.split_salt
    members = [key for key in pair_keys
               if split_of(salt, key, fractions) == "v1"]
    members.sort(key=lambda key: selection_key(salt, key))
    tail = members[scoring.validation.v1_pair_count:]
    needed = fit_config.fit.fit_count + fit_config.fit.holdout_count
    if len(tail) < needed:
        raise ValueError(
            f"the v1 tail holds {len(tail)} pairs, {needed} requested")
    tail.sort(key=lambda key: selection_key(fit_config.fit.split_salt, key))
    fit_keys = sorted(tail[:fit_config.fit.fit_count])
    holdout_keys = sorted(
        tail[fit_config.fit.fit_count:needed])
    return fit_keys, holdout_keys


def _labeled_trials(records: Sequence[tuple[str, JsonValue, str]],
                    context: ScoringContext,
                    encoders: Encoders) -> list[LabeledTrial]:
    harness.prewarm_records([record for _, record, _ in records],
                            context.gates, context.render, encoders)
    return [LabeledTrial(key=key,
                         standardized=standardized_scores(record, context,
                                                          encoders),
                         label=label)
            for key, record, label in records]


def _curve_rows(grid: Sequence[Mapping[str, float]],
                objective: Callable[[Mapping[str, float]], float],
                counts: Callable[[Mapping[str, float]], dict[str, int]],
                ) -> list[dict[str, JsonValue]]:
    rows = []
    for weights in grid:
        rows.append({"weights": dict(weights),
                     "objective": harness.quantized(objective(weights)),
                     "readable_trials": counts(weights)})
    return rows


def _winner(rows: list[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    """The first row with the highest objective.

    A written rule for rows with equal scores.
    """
    best = rows[0]
    for row in rows[1:]:
        if row["objective"] > best["objective"]:
            best = row
    return best


def _is_endpoint(weights: Mapping[str, float]) -> bool:
    """A winner with a zero weight cannot freeze (section 10.2)."""
    return any(weight == 0.0 for weight in weights.values())


@dataclass(frozen=True, slots=True)
class FitData:
    """The collected fit inputs, shared by the fit and the V4 harness.

    The two sources' trials hold their standardized channel scores,
    thus a grid point costs one fuse-and-rank step and the ablation
    harness re-runs the grid on channel subsets with no new encoding.
    """

    union_index: PoolIndex
    pool_index: PoolIndex
    source1_fit: tuple[LabeledTrial, ...]
    source1_holdout: tuple[LabeledTrial, ...]
    source2_fit: tuple[LabeledTrial, ...]
    source2_holdout: tuple[LabeledTrial, ...]
    placement_signal: float | None
    placement_alive: bool
    scoring_hash: str
    fit_hash: str
    commonness_hash: str
    generator_hash: str
    preparation_version_id: str
    fit_pair_count: int
    holdout_pair_count: int
    v1_pair_count: int
    union_contributors: Mapping[ChannelName, int]
    pool_contributors: Mapping[ChannelName, int]


def collect_fit_data(scoring: ScoringConfig, fit_config: FitConfig, *,
                     data_root: Path,
                     providers: Mapping[str, object] | None = None,
                     clock: Callable[[], str] | None = None) -> FitData:
    """The two sources' labeled trials, standardized for the grid."""
    providers = providers or {}
    clock = clock or harness.default_clock

    loaded = load_pool_index(Path(scoring.input.preparation_record),
                             data_root, dev_only=scoring.report.dev_only)
    prep_config = load_preparation_config(Path(loaded.record.config_path))
    _check_shared_space(scoring, prep_config)

    source = providers.get("sketch_pairs") or harness.wire_sketch_pairs(
        scoring, data_root)
    keys = harness.pair_keys_of(source)
    fit_keys, holdout_keys = fit_split_keys(keys, scoring, fit_config)
    pairs = harness.pairs_by_key(source, set(fit_keys) | set(holdout_keys))
    harness.check_selected_pairs(pairs, fit_keys + holdout_keys,
                                 intake_gates(scoring),
                                 loaded.render.canvas_px, "mixed")

    prepared_slots = ("line_drawer", "image_encoder", "describer",
                      "text_encoder")
    wired = {name: providers.get(name) or wire_slot(name, prep_config,
                                                    data_root)
             for name in prepared_slots}
    record_hashes = dict(loaded.record.provider_config_hashes)
    for slot_name in prepared_slots:
        measured = str(getattr(wired[slot_name], "config_hash"))
        if measured != record_hashes[slot_name]:
            raise ValueError(
                f"{slot_name}: wired hash {measured[:8]} does not agree "
                f"with the preparation record {record_hashes[slot_name][:8]} "
                "— the photograph path must equal the pool path (Rule 3)")

    slot_hashes = harness.scoring_provider_hashes(scoring, providers)
    harness.check_element_space(record_hashes, slot_hashes)
    dataset_hash = slot_hashes["sketch_pairs"]
    scoring_hash = scoring_config_hash(scoring, slot_hashes)
    fit_hash = fit_config_hash(fit_config)

    photo_bytes_by_id = {
        sha256_hex(pairs[key].photo_bytes): pairs[key].photo_bytes
        for key in fit_keys + holdout_keys}
    union_index = build_union_index(
        loaded, prep_config, photo_bytes_by_id, dataset_hash, data_root,
        wired["line_drawer"], wired["image_encoder"], wired["describer"],
        wired["text_encoder"])

    encoders = harness.wire_encoders(scoring, data_root, providers)
    gates = intake_gates(scoring)
    outline = outline_config(scoring)
    element = element_config(scoring)
    placement = placement_config(scoring)
    generator_hash = harness.resolved_generator_hash(
        scoring, loaded.index, data_root, providers.get("generalizer"))
    commonness_hash = commonness_config_hash(
        scoring, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], dataset_hash, generator_hash)
    weights = fusion_weights(scoring)

    # Source 2: labeled synthetic sets, plain pool, seed-disjoint
    # halves (spec section 10.1). Built before the commonness thunks
    # so a missing generalization table stops the run first — the
    # table build is a deliberate owner step (spec P4 §17a item 7).
    entry_count = len(loaded.index.pool_frequency)
    table = harness.stored_table(loaded.index, fit_config, data_root,
                                 providers.get("generalizer"))
    fit_synthetic = synthetic_set(
        loaded.index, fit_config, table, placement,
        seed=fit_config.fit.synthetic_seed,
        count=fit_config.fit.synthetic_count)
    holdout_synthetic = synthetic_set(
        loaded.index, fit_config, table, placement,
        seed=fit_config.fit.synthetic_seed + 1,
        count=fit_config.fit.synthetic_count)

    def background() -> list[tuple[str, JsonValue]]:
        return harness.full_background(
            scoring, source, scoring.validation.submission_mode,
            loaded.index, placement, data_root,
            providers.get("generalizer"))

    # The synthetic trials activate the element channel always, and at
    # relation levels the rectangle groups activate outline and the
    # relations activate placement — those channels then must have
    # tables, and a background that cannot supply them stops here.
    relation_levels = any(row.relations > 0
                          for row in fit_config.generator.levels)
    pool_required: tuple[ChannelName, ...] = ("element",)
    if relation_levels:
        pool_required = ("element", "outline", "placement")
    channel_names = tuple(sorted(set(weights) | {"placement"}))
    union_tables = ensure_commonness_tables(
        data_root=data_root, index=union_index,
        commonness_hash=commonness_hash, background=background,
        gates=gates, render=loaded.render, outline=outline, element=element,
        placement=placement, encoders=encoders,
        submission_mode=scoring.validation.submission_mode, clock=clock,
        required_channels=("outline", "element"))
    pool_tables = ensure_commonness_tables(
        data_root=data_root, index=loaded.index,
        commonness_hash=commonness_hash, background=background,
        gates=gates, render=loaded.render, outline=outline, element=element,
        placement=placement, encoders=encoders,
        submission_mode=scoring.validation.submission_mode, clock=clock,
        required_channels=pool_required)

    union_context = build_scoring_context(
        index=union_index, gates=gates, render=loaded.render,
        outline=outline, element=element, placement=placement,
        weights={name: 1.0 for name in channel_names},
        commonness=union_tables.tables,
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)
    pool_context = build_scoring_context(
        index=loaded.index, gates=gates, render=loaded.render,
        outline=outline, element=element, placement=placement,
        weights={name: 1.0 for name in channel_names},
        commonness=pool_tables.tables,
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)

    source1_fit = _labeled_trials(
        [(key, harness.submission_record(pairs[key], "mixed"),
          sha256_hex(pairs[key].photo_bytes)) for key in fit_keys],
        union_context, encoders)
    source1_holdout = _labeled_trials(
        [(key, harness.submission_record(pairs[key], "mixed"),
          sha256_hex(pairs[key].photo_bytes)) for key in holdout_keys],
        union_context, encoders)
    # The union photographs hold no boxes (spec P4 §17a item 6): a
    # union trial that activates placement scores relations against
    # geometry that is not there, and the run stops loudly.
    for trial in (*source1_fit, *source1_holdout):
        if "placement" in trial.standardized:
            raise ValueError(
                f"union trial {trial.key} activates placement, and the "
                "union photographs hold no boxes — build photograph "
                "boxes through the p07 slot first (spec P4 §17a item 6)")
    source2_fit = [
        replace(trial, level=row.level)
        for trial, row in zip(_labeled_trials(
            [(row.key, row.record, row.image_id) for row in fit_synthetic],
            pool_context, encoders), fit_synthetic)]
    source2_holdout = [
        replace(trial, level=row.level)
        for trial, row in zip(_labeled_trials(
            [(row.key, row.record, row.image_id)
             for row in holdout_synthetic],
            pool_context, encoders), holdout_synthetic)]

    # The placement signal test (D8, first half): placement alone on
    # the strong-level holdout synthetics that name a relation. The
    # level comes from the trial itself, not a positional pairing.
    strong = [trial for trial in source2_holdout
              if trial.level is not None and trial.level <= 1
              and "placement" in trial.standardized]
    placement_signal = None
    if strong:
        placement_signal = mean_trial_score(
            strong, {"placement": 1.0}, loaded.index)
    placement_alive = placement_signal is not None \
        and placement_signal >= fit_config.fit.signal_line

    return FitData(
        union_index=union_index,
        pool_index=loaded.index,
        source1_fit=tuple(source1_fit),
        source1_holdout=tuple(source1_holdout),
        source2_fit=tuple(source2_fit),
        source2_holdout=tuple(source2_holdout),
        placement_signal=placement_signal,
        placement_alive=placement_alive,
        scoring_hash=scoring_hash,
        fit_hash=fit_hash,
        commonness_hash=commonness_hash,
        generator_hash=generator_config_hash(
            fit_config,
            vocabulary_digest(loaded.index.vocabulary[:entry_count]),
            table_hash(table), placement.area_cap),
        preparation_version_id=loaded.record.preparation_version_id,
        fit_pair_count=len(fit_keys),
        holdout_pair_count=len(holdout_keys),
        v1_pair_count=scoring.validation.v1_pair_count,
        union_contributors=dict(union_tables.contributors),
        pool_contributors=dict(pool_tables.contributors),
    )


OBJECTIVE_BASES: tuple[str, ...] = ("source1", "mixed")


def _split_sources(data: FitData, trials: str,
                   ) -> tuple[tuple[LabeledTrial, ...],
                              tuple[LabeledTrial, ...]]:
    if trials == "fit":
        return data.source1_fit, data.source2_fit
    return data.source1_holdout, data.source2_holdout


def fit_objective(data: FitData, trials: str,
                  basis: str) -> Callable[[Mapping[str, float]], float]:
    """The §19 objective across one split ("fit" or "holdout").

    The basis is a property of the grid, and not of the candidate
    (ruling 2026-08-10): the two-channel line reads source 1 alone —
    the only labeled source where the outline channel holds signal —
    and the simplex mixes the two sources equally, because
    placement's labels are synthetic (D6). One basis across a grid
    keeps each cost and each point like-for-like.
    """
    if basis not in OBJECTIVE_BASES:
        raise ValueError(f"unknown objective basis: {basis!r}")
    source1, source2 = _split_sources(data, trials)

    def value(candidate: Mapping[str, float]) -> float:
        first = mean_trial_score(source1, candidate, data.union_index)
        if basis == "source1":
            return first
        second = mean_trial_score(source2, candidate, data.pool_index)
        return (first + second) / 2.0

    return value


def readable_counts(data: FitData, trials: str, basis: str,
                    ) -> Callable[[Mapping[str, float]], dict[str, int]]:
    """The count of trials each candidate reads, for the curve rows."""
    source1, source2 = _split_sources(data, trials)

    def counts(candidate: Mapping[str, float]) -> dict[str, int]:
        result = {"source1": sum(1 for trial in source1
                                 if readable_trial(trial, candidate))}
        if basis == "mixed":
            result["source2"] = sum(1 for trial in source2
                                    if readable_trial(trial, candidate))
        return result

    return counts


def run_fit(scoring: ScoringConfig, fit_config: FitConfig, *,
            data_root: Path, records_root: Path,
            providers: Mapping[str, object] | None = None,
            clock: Callable[[], str] | None = None,
            code_version: str = "dev") -> dict[str, JsonValue]:
    """One full fit: the two sources, the grid, the committed record."""
    clock = clock or harness.default_clock
    data = collect_fit_data(scoring, fit_config, data_root=data_root,
                            providers=providers, clock=clock)

    line = _curve_rows(grid_line(fit_config.fit.line_points),
                       fit_objective(data, "fit", "source1"),
                       readable_counts(data, "fit", "source1"))
    curve: dict[str, JsonValue] = {"line": line}
    winner = _winner(line)
    basis = "source1"
    if data.placement_alive:
        basis = "mixed"
        simplex = _curve_rows(grid_simplex(fit_config.fit.simplex_step),
                              fit_objective(data, "fit", "mixed"),
                              readable_counts(data, "fit", "mixed"))
        curve["simplex"] = simplex
        winner = _winner(simplex)
    holdout = fit_objective(data, "holdout", basis)

    winner_weights = {str(k): float(v) for k, v in winner["weights"].items()}
    endpoint = _is_endpoint(winner_weights)
    content: dict[str, JsonValue] = {
        "harness": "fit",
        "tag": fit_config.tag,
        "dev_only": scoring.report.dev_only,
        "scoring_config_hash": data.scoring_hash,
        "fit_config_hash": data.fit_hash,
        "commonness_config_hash": data.commonness_hash,
        "generator_config_hash": data.generator_hash,
        "index_id": data.pool_index.index_id,
        "union_index_id": data.union_index.index_id,
        "preparation_version_id": data.preparation_version_id,
        "fit_pair_count": data.fit_pair_count,
        "holdout_pair_count": data.holdout_pair_count,
        # The fit-tail split starts after the recorded gate pairs,
        # thus the record pins the boundary value it was cut with.
        "v1_pair_count": data.v1_pair_count,
        "synthetic_count": fit_config.fit.synthetic_count,
        "commonness_contributors": {
            "union": dict(data.union_contributors),
            "pool": dict(data.pool_contributors)},
        "curve": curve,
        "winner": winner,
        "objective_basis": basis,
        "holdout_objective": harness.quantized(holdout(winner_weights)),
        "placement_signal": (None if data.placement_signal is None
                             else harness.quantized(data.placement_signal)),
        "placement_signal_line": fit_config.fit.signal_line,
        "placement_alive": data.placement_alive,
        "endpoint": endpoint,
        "freeze_blocked": endpoint,
        "created_at": clock(),
        "code_version": code_version,
        **harness.VERDICT_TEMPLATE,
    }
    label = f"fit-{fit_config.tag}-{data.fit_hash[:8]}"
    path = records_root / f"{label}.json"
    if not (path.is_file() and _kept_verdict(path, content)):
        write_json_pretty(path, content)
    content["record_path"] = str(path)
    return content


def _kept_verdict(path: Path, content: dict[str, JsonValue]) -> bool:
    """Keep a filled verdict when the record names this run's identity.

    The P2 rule: a re-run must not move a recorded decision back to
    pending. The identity covers the full lineage — a moved
    generator, commonness, union, or preparation identity raises,
    because a kept stale curve hides a data change behind a filled
    verdict.
    """
    import json

    existing = json.loads(path.read_text(encoding="utf-8"))
    if existing.get("verdict") == harness.VERDICT_TEMPLATE["verdict"]:
        return False
    for name in ("scoring_config_hash", "fit_config_hash", "index_id",
                 "union_index_id", "preparation_version_id",
                 "commonness_config_hash", "generator_config_hash"):
        if existing.get(name) != content.get(name):
            raise ValueError(
                f"{path}: a record with a filled verdict names a different "
                f"{name} — move the old record aside before this run")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.fit")
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
    content = run_fit(scoring, fit_config,
                      data_root=Path(arguments.data_root),
                      records_root=Path(arguments.records_root))
    if arguments.report:
        winner = content["winner"]
        print(f"fit {content['fit_config_hash'][:8]} "
              f"winner={winner['weights']} "
              f"objective={winner['objective']}")
        print(f"holdout_objective={content['holdout_objective']}")
        print(f"placement_signal={content['placement_signal']} "
              f"alive={content['placement_alive']}")
        print(f"endpoint={content['endpoint']} "
              f"freeze_blocked={content['freeze_blocked']}")
        print(f"record={content['record_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
