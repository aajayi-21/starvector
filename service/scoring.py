"""Provider wiring and the close-time scoring computation.

Spec: S1 (in docs/specs/) sections 6 and 7. The wiring follows the
demo-tool sequence (spec T1), with one difference: the server does
not build a commonness table and does not encode at open - a cold
lineage stops loudly with the build command named (R5). The scoring
itself is pipeline.score.score_trial plus the V1 report pattern, and
no formula lives here (R9).
"""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from core.canonical import JsonValue
from core.channels.element import match_report
from core.intake import validate_submission
from core.types import MatchRow, ScoringContext, TargetId, TrialScore
from pipeline.commonness import (commonness_config_hash,
                                 ensure_commonness_tables)
from pipeline.config import (ScoringConfig, element_config, fusion_weights,
                             intake_gates, outline_config, placement_config,
                             scoring_config_hash)
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import Encoders, encode_submission, score_trial
from validation import harness

# The one-time table build the R5 refusal names: a warm validation.v2
# run builds the mixed commonness tables at near zero posts.
TABLES_COMMAND = "uv run python -m validation.v2 --config {config}"


class WiredScoring(NamedTuple):
    """One wired scoring surface: the context plus its identity."""

    context: ScoringContext
    encoders: Encoders
    scoring_hash: str
    commonness_hash: str
    preparation_version_id: str


def _refusing_background(config_path: str) -> Callable[[], list]:
    """A background thunk that stops a cold table build (R5)."""

    def background() -> list:
        raise ValueError(
            "the commonness tables are not built for this scoring config "
            f"- run `{TABLES_COMMAND.format(config=config_path)}` (a warm "
            "run at near zero posts), then open the day again (S1 R5)")

    return background


class _RefusesEncode:
    """Encoder stubs for open: the warm path encodes nothing (R5)."""

    config_hash = "open-encodes-nothing"

    def encode_images(self, images: Sequence[bytes]):
        raise ValueError("open encodes nothing - the warm table read "
                         "needs no encoder (S1 R5)")

    def encode_texts(self, texts: Sequence[str]):
        raise ValueError("open encodes nothing - the warm table read "
                         "needs no encoder (S1 R5)")


def _wire(config: ScoringConfig, config_path: str, data_root: Path,
          encoders: Encoders,
          providers: Mapping[str, object] | None) -> WiredScoring:
    """The shared wiring sequence (the demo-tool shape, warm-only)."""
    providers = providers or {}
    loaded = load_pool_index(Path(config.input.preparation_record),
                             data_root, dev_only=config.report.dev_only)
    slot_hashes = harness.scoring_provider_hashes(config, providers)
    harness.check_element_space(dict(loaded.record.provider_config_hashes),
                                slot_hashes)
    scoring_hash = scoring_config_hash(config, slot_hashes)
    generator_hash = harness.resolved_generator_hash(
        config, loaded.index, data_root, providers.get("generalizer"))
    commonness_hash = commonness_config_hash(
        config, loaded.render, slot_hashes["sketch_encoder"],
        slot_hashes["text_encoder"], slot_hashes["sketch_pairs"],
        generator_hash)
    weights = fusion_weights(config)
    tables = ensure_commonness_tables(
        data_root=data_root, index=loaded.index,
        commonness_hash=commonness_hash,
        background=_refusing_background(config_path),
        gates=intake_gates(config), render=loaded.render,
        outline=outline_config(config), element=element_config(config),
        placement=placement_config(config), encoders=encoders,
        submission_mode=config.validation.submission_mode,
        clock=harness.default_clock,
        # Each weighted channel must have a table: the server scores
        # arbitrary player mixtures (Rule 5), not one harness mode.
        required_channels=tuple(sorted(weights)))
    context = build_scoring_context(
        index=loaded.index, gates=intake_gates(config),
        render=loaded.render, outline=outline_config(config),
        element=element_config(config), placement=placement_config(config),
        weights=weights, commonness=tables.tables,
        scoring_config_hash=scoring_hash,
        commonness_config_hash=commonness_hash)
    return WiredScoring(
        context=context, encoders=encoders, scoring_hash=scoring_hash,
        commonness_hash=commonness_hash,
        preparation_version_id=loaded.record.preparation_version_id)


def wire_for_open(config: ScoringConfig, config_path: str,
                  data_root: Path) -> WiredScoring:
    """The open-time wiring: warm reads alone, no encoder, no spend."""
    stub = _RefusesEncode()
    return _wire(config, config_path, data_root,
                 Encoders(sketch=stub, text=stub), providers=None)


def wire_for_close(config: ScoringConfig, config_path: str,
                   data_root: Path,
                   providers: Mapping[str, object] | None = None,
                   ) -> WiredScoring:
    """The close-time wiring: live encoders, tables read warm."""
    encoders = harness.wire_encoders(config, data_root, providers)
    return _wire(config, config_path, data_root, encoders, providers)


def score_stored_submission(record: JsonValue, target_id: TargetId,
                            wired: WiredScoring,
                            ) -> tuple[TrialScore, tuple[MatchRow, ...]]:
    """One stored record to its trial score and atom-by-atom report.

    The report re-validates and re-encodes the submission (the V1
    pattern - the provider answers the second batch from its cache),
    because the Layer 8 contract stays as it is.
    """
    trial = score_trial(record, target_id, wired.context, wired.encoders)
    submission = validate_submission(record, wired.context.gates,
                                     wired.context.render.canvas_px)
    encoded = encode_submission(submission, wired.context.render,
                                wired.encoders)
    position = wired.context.index.image_ids.index(target_id)
    report = match_report(encoded, wired.context.index, position,
                          wired.context.element)
    return trial, report


def dev_rankings(record: JsonValue, target_id: TargetId,
                 wired: WiredScoring) -> dict[str, JsonValue]:
    """Score one draft against the full pool, storing nothing.

    The dev-mode surface (section 14b ruling, 2026-08-12): the
    owner tests the scoring by eye, thus the answer holds the trial
    numbers plus the full fused ordering with the target marked. The
    draft is not stored, the day does not move, and the computation
    is the production path - validate, encode, the weighted
    channels, fusion, rank.
    """
    import numpy as np

    from core.fusion import fuse
    from core.ranking import decoy_set, rank
    from pipeline.score import standardized_channels

    context = wired.context
    submission = validate_submission(record, context.gates,
                                     context.render.canvas_px)
    encoded = encode_submission(submission, context.render, wired.encoders)
    fused = fuse(standardized_channels(encoded, context), context.weights)
    trial = rank(fused, target_id, decoy_set(context.index, target_id),
                 context.index)
    order = np.argsort(-fused, kind="stable")            # (N,) positions
    rankings: list[JsonValue] = []
    target_position = 0
    for position, index in enumerate(order, start=1):
        image_id = context.index.image_ids[int(index)]
        if image_id == target_id:
            target_position = position
        rankings.append({
            "position": position,
            "image_id": image_id,
            "fused": harness.quantized(float(fused[int(index)])),
            "is_target": image_id == target_id,
        })
    return {
        "trial": {"p": harness.quantized(trial.p),
                  "decoy_count": trial.decoy_count,
                  "beaten": trial.beaten, "tied": trial.tied,
                  "target_rank": trial.decoy_count - trial.beaten
                  - trial.tied + 1},
        "target_position": target_position,
        "rankings": rankings,
    }


def trial_row_value(day: str, player: str, trial_id: str,
                    trial: TrialScore, report: tuple[MatchRow, ...],
                    wired: WiredScoring) -> dict[str, JsonValue]:
    """The stored trial-row document (S1 section 5).

    One function shapes the row for close and for rescore, thus the
    R8 byte equality holds by construction. The strict rank is the
    V1 rule: decoys above the target, plus one.
    """
    return {
        "day": day,
        "player": player,
        "trial_id": trial_id,
        "p": harness.quantized(trial.p),
        "decoy_count": trial.decoy_count,
        "beaten": trial.beaten,
        "tied": trial.tied,
        "target_rank": trial.decoy_count - trial.beaten - trial.tied + 1,
        "report": [
            {"atom_id": row.atom_id, "atom_text": row.atom_text,
             "element": row.element,
             "weight": harness.quantized(row.weight),
             "similarity": harness.quantized(row.similarity),
             "rarity": harness.quantized(row.rarity)}
            for row in report
        ],
        "scoring_config_hash": wired.scoring_hash,
        "commonness_config_hash": wired.commonness_hash,
        "preparation_version_id": wired.preparation_version_id,
    }
