"""The V6 harness: does the fast path find the right candidates?

Spec P4 §11 (R7, D10). On labeled synthetic submissions, the fraction
of known targets in the element channel's tier-1 shortlist and in the
accurate tier-2 head, at the ruled widths. A dev pool has some
hundreds of images, thus the production thresholds (500 / 25) are
trivial here — these are dev-only numbers that make the tier
interface earn its keep, and the production line waits for Phase 5.
"""

import argparse
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np

from core.channels.element import (element_atoms, element_channel,
                                   rarity_weights, similarity_table,
                                   tier1_scores)
from core.intake import validate_submission
from core.canonical import JsonValue
from pipeline.config import (ConfigError, ScoringConfig, element_config,
                             intake_gates, load_scoring_config,
                             placement_config, scoring_config_hash)
from pipeline.context import load_pool_index
from pipeline.score import encode_submission
from pool.artifacts import write_json_pretty
from validation import harness
from validation.fitconfig import FitConfig, fit_config_hash, load_fit_config
from validation.generalize import table_hash, vocabulary_digest
from validation.generator import generator_config_hash, synthetic_set
from validation.v3 import fit_harness_hash


def run_v6(config: ScoringConfig, fit_config: FitConfig, *,
           data_root: Path, records_root: Path,
           providers: Mapping[str, object] | None = None,
           clock: Callable[[], str] | None = None,
           code_version: str = "dev") -> dict[str, JsonValue]:
    """One full V6 run: tier recall at the ruled widths, record."""
    providers = providers or {}
    clock = clock or harness.default_clock

    loaded = load_pool_index(Path(config.input.preparation_record),
                             data_root, dev_only=config.report.dev_only)
    encoders = harness.wire_encoders(config, data_root, providers)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    harness.check_element_space(dict(loaded.record.provider_config_hashes),
                                slot_hashes)
    scoring_hash = scoring_config_hash(config, slot_hashes)
    fit_hash = fit_config_hash(fit_config)
    harness_hash = fit_harness_hash("v6", scoring_hash, fit_hash)
    gates = intake_gates(config)
    element = element_config(config)
    placement = placement_config(config)

    entry_count = len(loaded.index.pool_frequency)
    # The stored table alone — the build is a deliberate owner step
    # (spec P4 §17a, build-settled item 7).
    table = harness.stored_table(loaded.index, fit_config, data_root,
                                 providers.get("generalizer"))
    # The identity of the trial sets this run scores (§14): the record
    # must pin the generator hash, the seed, and the count.
    trial_generator_hash = generator_config_hash(
        fit_config,
        vocabulary_digest(loaded.index.vocabulary[:entry_count]),
        table_hash(table), placement)

    position_of = {image_id: position for position, image_id
                   in enumerate(loaded.index.image_ids)}
    tier1_hits = {width: 0 for width in fit_config.harness.v6_tier1_widths}
    tier2_hits = {width: 0 for width in fit_config.harness.v6_tier2_widths}
    trial_count = 0
    # The levels V6 reads come from the fit config (ruling
    # 2026-08-10): recall of a noise submission's source image
    # measures nothing, thus the committed value names levels 0 and 1.
    for level in fit_config.harness.v6_levels:
        rows = synthetic_set(
            loaded.index, fit_config, table, placement,
            seed=fit_config.harness.v6_seed,
            count=fit_config.harness.v6_trial_count,
            level_index=level)
        harness.prewarm_records([row.record for row in rows], gates,
                                loaded.render, encoders)
        for row in rows:
            submission = validate_submission(row.record, gates,
                                             loaded.render.canvas_px)
            encoded = encode_submission(submission, loaded.render, encoders)
            atoms = element_atoms(encoded)
            if not atoms:
                continue
            vectors = np.stack([encoded.vectors[atom.id] for atom in atoms])
            similarity = similarity_table(vectors,
                                          loaded.index.vocabulary_vectors,
                                          loaded.index.element_space_mean)
            rarity = rarity_weights(similarity[:, :entry_count],
                                    loaded.index.pool_frequency,
                                    loaded.index.pool_image_count)
            tier1 = tier1_scores(similarity, rarity, loaded.index.incidence)
            exact = element_channel(encoded, loaded.index, element)
            target = position_of[row.image_id]
            tier1_order = np.argsort(-tier1, kind="stable")
            exact_order = np.argsort(-exact, kind="stable")
            tier1_rank = int(np.where(tier1_order == target)[0][0]) + 1
            exact_rank = int(np.where(exact_order == target)[0][0]) + 1
            trial_count += 1
            for width in tier1_hits:
                if tier1_rank <= width:
                    tier1_hits[width] += 1
            for width in tier2_hits:
                if exact_rank <= width:
                    tier2_hits[width] += 1

    aggregates: dict[str, JsonValue] = {
        "trial_count": trial_count,
        "levels": list(fit_config.harness.v6_levels),
        "tier1_recall": {
            str(width): harness.quantized(tier1_hits[width] / trial_count)
            for width in fit_config.harness.v6_tier1_widths},
        "tier2_recall": {
            str(width): harness.quantized(tier2_hits[width] / trial_count)
            for width in fit_config.harness.v6_tier2_widths},
    }
    directory = harness.validation_dir(data_root, "v6",
                                       loaded.index.index_id, harness_hash)
    write_json_pretty(directory / "report.json", aggregates)
    meta: dict[str, JsonValue] = {
        "harness": "v6",
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "fit_config_hash": fit_hash,
        "generator_config_hash": trial_generator_hash,
        "created_at": clock(),
        "code_version": code_version,
    }
    write_json_pretty(directory / "meta.json", meta)

    content: dict[str, JsonValue] = {
        "harness": "v6",
        "tag": fit_config.tag,
        "dev_only": config.report.dev_only,
        **aggregates,
        "index_id": loaded.index.index_id,
        "harness_config_hash": harness_hash,
        "scoring_config_hash": scoring_hash,
        "fit_config_hash": fit_hash,
        "generator_config_hash": trial_generator_hash,
        "synthetic_seed": fit_config.harness.v6_seed,
        "synthetic_count": fit_config.harness.v6_trial_count,
        "preparation_version_id": loaded.record.preparation_version_id,
        "created_at": clock(),
        "code_version": code_version,
        **harness.VERDICT_TEMPLATE,
    }
    record_path = harness.write_harness_record(
        records_root, "v6", fit_config.tag, harness_hash, content)
    content["record_path"] = str(record_path)
    return content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.v6")
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
    content = run_v6(scoring, fit_config,
                     data_root=Path(arguments.data_root),
                     records_root=Path(arguments.records_root))
    if arguments.report:
        print(f"trials={content['trial_count']} levels={content['levels']}")
        print(f"tier1_recall={content['tier1_recall']}")
        print(f"tier2_recall={content['tier2_recall']}")
        print(f"record={content['record_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
