"""Layer 2 encode step and the trial orchestration.

Spec: docs/specs/scoring-path.md section 10. score_trial runs the
layers in sequence: intake, atom assembly, encode, each active
channel, normalization, fusion, ranking. The target argument goes to
the Layer 8 functions and to nothing before them (Rule 1) — the test
suite scans this module for that property.
"""

from core.canonical import JsonValue
from core.channels.outline import outline_channel
from core.fusion import active_channels, fuse
from core.intake import render_strokes, validate_submission
from core.normalize import commonness_correct, standardize
from core.ranking import decoy_set, rank
from core.types import (ROUTING_TABLE, ChannelName, EncodedSubmission,
                        PoolScores, RenderParams, ScoringContext, Submission,
                        TargetId, TrialScore)
from providers.protocols import SketchEncoder


def encode_submission(submission: Submission, render: RenderParams,
                      encoder: SketchEncoder) -> EncodedSubmission:
    """Render and encode the atoms the routing table sends anywhere.

    One batched encoder use. In this phase the routed set is the
    drawing atoms — DESCRIPTION and RELATION atoms have no built
    channel in the routing table and get no vector (data-driven, not
    a modality branch). An empty routed set makes no encoder use at
    all.
    """
    routed = [atom for atom in submission.atoms if ROUTING_TABLE[atom.type]]
    if not routed:
        return EncodedSubmission(atoms=submission.atoms, vectors={})
    renders = []
    for atom in routed:
        if atom.strokes is None:
            raise ValueError(f"atom {atom.id} routes to a channel but has "
                             "no strokes")
        renders.append(render_strokes(atom.strokes, render.canvas_px,
                                      render.line_width_px))
    vectors = encoder.encode_images(renders)   # (B, d)
    if vectors.shape[0] != len(routed):
        raise ValueError(
            f"encoder returned {vectors.shape[0]} rows for {len(routed)} "
            "inputs")
    return EncodedSubmission(
        atoms=submission.atoms,
        vectors={atom.id: vectors[position]
                 for position, atom in enumerate(routed)},
    )


def _run_channel(name: ChannelName, encoded: EncodedSubmission,
                 context: ScoringContext) -> PoolScores:
    match name:
        case "outline":
            return outline_channel(encoded, context.index, context.outline)
        case _:
            raise ValueError(f"unknown channel: {name!r}")


def score_trial(record: JsonValue, target: TargetId,
                context: ScoringContext,
                encoder: SketchEncoder) -> TrialScore:
    """One submission record to one trial score, layers 0 through 8.

    The record is the frozen wire shape. The context carries the pool
    index and the configuration surface. The encoder is the wired
    SketchEncoder slot. Raises IntakeError on a gate violation and
    NoActiveChannels when no built channel reads the submission.
    """
    submission = validate_submission(record, context.gates,
                                     context.render.canvas_px)
    encoded = encode_submission(submission, context.render, encoder)
    active = active_channels(encoded.atoms, ROUTING_TABLE)
    standardized: dict[ChannelName, PoolScores] = {}
    for name in sorted(active):
        raw = _run_channel(name, encoded, context)
        if name not in context.commonness:
            raise ValueError(f"channel {name!r} has no commonness table")
        corrected = commonness_correct(raw, context.commonness[name])
        standardized[name] = standardize(corrected)
    fused = fuse(standardized, context.weights)
    decoys = decoy_set(context.index, target)
    return rank(fused, target, decoys, context.index)
