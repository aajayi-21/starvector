"""Layer 2 encode step and the trial orchestration.

Spec: docs/specs/scoring-path.md section 10 and
docs/specs/element-channel.md section 10. score_trial runs the layers
in sequence: intake, atom assembly, encode, each active channel,
normalization, fusion, ranking. The target argument goes to the Layer 8
functions and to nothing before them (Rule 1) — the test suite scans
this module for that property.
"""

from collections.abc import Sequence
from typing import NamedTuple

from core.canonical import JsonValue
from core.channels.element import element_channel
from core.channels.outline import outline_channel
from core.channels.placement import placement_channel
from core.fusion import active_channels, fuse
from core.intake import render_strokes, validate_submission
from core.normalize import commonness_correct, standardize
from core.ranking import decoy_set, rank
from core.types import (ROUTING_TABLE, Atom, ChannelName, ElementConfig,
                        EncodedSubmission, OutlineConfig, PlacementConfig,
                        PoolIndex, PoolScores, RenderParams, ScoringContext,
                        Submission, TargetId, TrialScore)
from providers.protocols import SketchEncoder, TextEncoder

# How many payloads go to a provider in one batch. Providers chunk
# again internally. This is the limit on what one batch holds.
ENCODE_BATCH = 64


class Encoders(NamedTuple):
    """The wired Layer 2 slots (spec P3 section 10).

    Two slots, because the atom payloads are of two kinds. Which slot
    an atom uses follows from its type, not from what the full
    submission contains (Rule 5).
    """

    sketch: SketchEncoder
    text: TextEncoder


class _Payloads(NamedTuple):
    """Routed atoms split by the slot that encodes them."""

    drawing: list[tuple[int, Atom, bytes]]
    text: list[tuple[int, Atom, str]]


def _routed_payloads(submissions: Sequence[Submission],
                     render: RenderParams) -> _Payloads:
    """Collect the payload of each routed atom across the submissions.

    A routed atom is one with a type that has a built channel in the
    routing table. A DESCRIPTION atom without text carries nothing at alpha 1.0
    and gets no vector, which is what keeps a labeled stroke group out
    of the element channel (D10).
    """
    payloads = _Payloads(drawing=[], text=[])
    for number, submission in enumerate(submissions):
        for atom in submission.atoms:
            if not ROUTING_TABLE[atom.type]:
                continue
            match atom.type:
                case "WHOLE-DRAWING":
                    if atom.strokes is None:
                        raise ValueError(
                            f"atom {atom.id} routes to a channel but has "
                            "no strokes")
                    payloads.drawing.append((number, atom, render_strokes(
                        atom.strokes, render.canvas_px, render.line_width_px)))
                case "DESCRIPTION":
                    if atom.text is not None:
                        payloads.text.append((number, atom, atom.text))
                case "RELATION":
                    # Read directly by the placement channel, not
                    # encoded (architecture section 6).
                    pass
                case _:
                    raise ValueError(
                        f"atom type {atom.type} routes to a channel and has "
                        "no encoder slot")
    return payloads


def _encode_in_batches(entries: list, encode, kind: str,
                       vectors: list[dict]) -> None:
    """Encode one slot's payloads in batches and file the rows.

    entries holds (submission number, atom, payload) rows. encode takes
    a sequence of payloads and returns one row for each. A row count
    that does not agree raises: a short answer can let an atom stay
    silently unencoded.
    """
    for start in range(0, len(entries), ENCODE_BATCH):
        chunk = entries[start:start + ENCODE_BATCH]
        rows = encode([payload for _, _, payload in chunk])    # (B, d)
        if rows.shape[0] != len(chunk):
            raise ValueError(
                f"the {kind} encoder returned {rows.shape[0]} rows for "
                f"{len(chunk)} inputs")
        for position, (number, atom, _) in enumerate(chunk):
            vectors[number][atom.id] = rows[position]


def encode_submissions(submissions: Sequence[Submission],
                       render: RenderParams,
                       encoders: Encoders) -> tuple[EncodedSubmission, ...]:
    """Encode many submissions with batched provider calls.

    The batching is across submissions, not in one, because the
    commonness build encodes a thousand background submissions and one
    batch for each of them can multiply the count of provider calls
    (U1). A slot with no payload is not called at all.
    """
    payloads = _routed_payloads(submissions, render)
    vectors: list[dict] = [{} for _ in submissions]
    if payloads.drawing:
        _encode_in_batches(payloads.drawing, encoders.sketch.encode_images,
                           "sketch", vectors)
    if payloads.text:
        _encode_in_batches(payloads.text, encoders.text.encode_texts,
                           "text", vectors)
    return tuple(
        EncodedSubmission(atoms=submission.atoms, vectors=vectors[number])
        for number, submission in enumerate(submissions))


def encode_submission(submission: Submission, render: RenderParams,
                      encoders: Encoders) -> EncodedSubmission:
    """Encode the atoms the routing table sends to a built channel."""
    return encode_submissions((submission,), render, encoders)[0]


def channel_scores(name: ChannelName, submission: EncodedSubmission,
                   index: PoolIndex, outline: OutlineConfig,
                   element: ElementConfig,
                   placement: PlacementConfig) -> PoolScores:
    """Run one built channel and give its raw scores, shape (N,).

    The configuration arrives as arguments rather than as a scoring
    context, because the commonness build needs channel scores before a
    context exists.
    """
    match name:
        case "outline":
            return outline_channel(submission, index, outline)
        case "element":
            return element_channel(submission, index, element)
        case "placement":
            return placement_channel(submission, index, placement)
        case _:
            raise ValueError(f"unknown channel: {name!r}")


def score_trial(record: JsonValue, target: TargetId,
                context: ScoringContext,
                encoders: Encoders) -> TrialScore:
    """One submission record to one trial score, layers 0 through 8.

    The record is the frozen wire shape. The context carries the pool
    index and the configuration surface. The encoders are the wired
    Layer 2 slots. Raises IntakeError on a gate violation and
    NoActiveChannels when no built channel reads the submission.
    """
    submission = validate_submission(record, context.gates,
                                     context.render.canvas_px)
    encoded = encode_submission(submission, context.render, encoders)
    active = active_channels(encoded, ROUTING_TABLE)
    standardized: dict[ChannelName, PoolScores] = {}
    for name in sorted(active):
        raw = channel_scores(name, encoded, context.index, context.outline,
                             context.element, context.placement)
        if name not in context.commonness:
            raise ValueError(f"channel {name!r} has no commonness table")
        corrected = commonness_correct(raw, context.commonness[name])
        standardized[name] = standardize(corrected)
    fused = fuse(standardized, context.weights)
    decoys = decoy_set(context.index, target)
    return rank(fused, target, decoys, context.index)
