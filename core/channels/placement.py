"""Layer 4 placement channel: stated relations against element boxes.

Implements docs/ARCHITECTURE.md section 12.3 through
docs/specs/fuse-and-validate.md section 9. A channel is a function of
(submission, pool): one number for each pool image, and the image that
hides behind the identifier is not an input (Rule 1). No provider, no
file access, no modality branch.

The architecture marks this channel optional and prescribes the exit:
if it proves fiddly, cut it and keep the RELATION atom type. The cut
criterion is written in the spec (D8), and a cut is a recorded ruling,
not a deletion of this module.
"""

import numpy as np

from core.channels.element import similarity_table
from core.types import (Atom, EncodedSubmission, FloatArray, PlacementConfig,
                        PoolIndex, PoolScores)

CHECK_RULES: tuple[str, ...] = ("axis-ramp-v1",)

# The four relation strings this build reads (D4). The vocabulary in
# the config must be a subset — scoring cannot check a relation it has
# no rule for.
KNOWN_RELATIONS: tuple[str, ...] = ("left-of", "right-of", "above", "below")


def _checked_config(config: PlacementConfig) -> None:
    """Stop on a configuration this module does not implement."""
    if config.check_rule not in CHECK_RULES:
        raise ValueError(f"unknown check_rule: {config.check_rule!r}")
    unknown = sorted(set(config.relation_vocabulary) - set(KNOWN_RELATIONS))
    if unknown:
        raise ValueError(
            f"relation_vocabulary holds unknown relations: {unknown}")
    if not 0.0 < config.area_cap <= 1.0:
        raise ValueError(f"area_cap must be in (0, 1], got {config.area_cap}")
    if not 0.0 < config.margin <= 1.0:
        raise ValueError(f"margin must be in (0, 1], got {config.margin}")


def relation_atoms(submission: EncodedSubmission,
                   config: PlacementConfig) -> tuple[Atom, ...]:
    """The RELATION atoms this channel reads.

    An atom with a relation string that is not in the vocabulary
    does not fire — scoring has no rule for it, and with the sum it
    adds zero (spec P4 section 9.1). The selection here
    keeps each RELATION atom because dropping one adds a branch that
    changes no score.
    """
    return tuple(atom for atom in submission.atoms
                 if atom.type == "RELATION")


def stroke_bounding_box(strokes: tuple[tuple[tuple[float, float], ...], ...],
                        ) -> tuple[float, float, float, float]:
    """The canvas bounding box of one atom's strokes, unit square."""
    xs = [x for stroke in strokes for x, _ in stroke]
    ys = [y for stroke in strokes for _, y in stroke]
    if not xs:
        raise ValueError("no points in the stroke set")
    return (min(xs), min(ys), max(xs), max(ys))


def box_area(box: tuple[float, float, float, float]) -> float:
    """The area of one box in the unit square."""
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def soft_check(relation: str, box_a: tuple[float, float, float, float],
               box_b: tuple[float, float, float, float],
               margin: float) -> float:
    """Rule axis-ramp-v1 (D4): a smooth check of one relation (R9).

    For left-of, the signed center distance cx_b - cx_a maps through a
    linear ramp that is 0 at -margin, 0.5 at 0, and 1 at +margin,
    clamped to [0, 1]. The other three relations are the same rule on
    the mirrored or vertical axis. Near 1 when the relation clearly
    holds, near 0 when it clearly does not, smooth in between — no
    hard boolean enters a score (I2).
    """
    center_a = ((box_a[0] + box_a[2]) / 2.0, (box_a[1] + box_a[3]) / 2.0)
    center_b = ((box_b[0] + box_b[2]) / 2.0, (box_b[1] + box_b[3]) / 2.0)
    match relation:
        case "left-of":
            signed = center_b[0] - center_a[0]
        case "right-of":
            signed = center_a[0] - center_b[0]
        case "above":
            # The canvas y axis points down (P2 decision D2), thus "a
            # above b" means center_a has the smaller y.
            signed = center_b[1] - center_a[1]
        case "below":
            signed = center_a[1] - center_b[1]
        case _:
            raise ValueError(f"unknown relation: {relation!r}")
    return min(1.0, max(0.0, 0.5 + signed / (2.0 * margin)))


def atom_boxes(submission: EncodedSubmission, index: PoolIndex,
               position: int, config: PlacementConfig,
               ) -> dict[str, tuple[float, float, float, float]]:
    """The located atoms of one submission in the image at position.

    A text-bearing DESCRIPTION atom — one with a Layer 2 vector —
    locates through the image: the box of its best-matching element
    in this image, when that slot holds a box with an area below
    area_cap — a near-full-frame box says nothing about placement
    (D4). This is what makes the check image-dependent: the claim
    "A left of B" scores against where this image puts A and B. When
    the matched slot has no usable box, the atom has no location in
    this image, and its relations add zero there (architecture
    section 12.3) — a fallback on that condition made missing
    detector data score as agreement, which the review caught.

    A strokes-only DESCRIPTION atom — one with no vector — locates
    by its stroke bounding box on the canvas: the outline channel's
    premise, that the canvas is the image frame, applied here. The
    path selection reads the submission alone, thus a relation
    between two canvas-located atoms scores the same value in each
    image and moves no ranking (Rule 2) — it is kept because
    dropping it adds a branch that changes no score. An atom that
    locates by no rule above has no entry.
    """
    text_atoms = tuple(atom for atom in submission.atoms
                       if atom.type == "DESCRIPTION"
                       and atom.id in submission.vectors)
    boxes: dict[str, tuple[float, float, float, float]] = {}

    if text_atoms:
        vectors = np.stack([submission.vectors[atom.id]
                            for atom in text_atoms])           # (m, d)
        row = index.incidence[position]                         # (k,)
        kept = row >= 0
        columns = np.where(kept)[0]
        bank = index.vocabulary_vectors[row[columns]]           # (k', d)
        similarity = similarity_table(vectors, bank,
                                      index.element_space_mean)  # (m, k')
        for number, atom in enumerate(text_atoms):
            # Equal values resolve to the lowest slot, as in P3.
            best = int(np.argmax(similarity[number]))
            slot = int(columns[best])
            if not bool(index.box_mask[position, slot]):
                continue
            box = tuple(float(value)
                        for value in index.box_table[position, slot])
            if box_area(box) >= config.area_cap:
                continue
            boxes[atom.id] = box

    for atom in submission.atoms:
        if (atom.type == "DESCRIPTION" and atom.strokes is not None
                and atom.id not in submission.vectors):
            boxes[atom.id] = stroke_bounding_box(atom.strokes)
    return boxes


def placement_scores(submission: EncodedSubmission, index: PoolIndex,
                     position: int, config: PlacementConfig,
                     relations: tuple[Atom, ...]) -> float:
    """The channel score of one image (spec P4 section 9.1).

    The sum of soft_check across relations that fire. A relation
    with no rule for its string, or with a referent that has no
    location in this image, adds zero — it does not abstain, and it
    cannot move the score (architecture section 12.3). A
    stated-count denominator looked cosmetic and was not: a
    submission-only multiplicative term is not neutral through the
    commonness correction, and the review measured it moving trial
    scores (ruling 2026-08-10). A fraction for display is a report
    task after fusion.
    """
    located = atom_boxes(submission, index, position, config)
    total = 0.0
    for atom in relations:
        if atom.relation not in config.relation_vocabulary:
            continue
        if atom.refers_to is None:
            raise ValueError(
                f"RELATION atom {atom.id!r} names no referents")
        first, second = atom.refers_to
        if first not in located or second not in located:
            continue
        total += soft_check(atom.relation, located[first], located[second],
                            config.margin)
    return total


def placement_channel(submission: EncodedSubmission, index: PoolIndex,
                      config: PlacementConfig) -> PoolScores:
    """Score the stated relations against each image's element boxes.

    Output shape (N,), float32. Raises when the submission states no
    relation — activation stops such a run from happening, and a silent
    zero vector here is a plausible number that is incorrect.
    """
    _checked_config(config)
    relations = relation_atoms(submission, config)
    if not relations:
        raise ValueError(
            "the placement channel needs one RELATION atom, got none")
    count = len(index.image_ids)
    scores = np.zeros(count, dtype=np.float64)                  # (N,)
    for position in range(count):
        scores[position] = placement_scores(submission, index, position,
                                            config, relations)
    return scores.astype(np.float32)                            # (N,)
