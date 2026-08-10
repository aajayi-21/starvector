"""Shared type aliases and frozen records for the scoring path.

The glossary in docs/ARCHITECTURE.md section 2 defines the data objects,
and docs/specs/scoring-path.md section 10 defines the scoring records.
Modules in core, pipeline, pool, and providers import these types, and
array shapes stay documented by the type annotations. This module holds
data shapes only — no behavior.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NamedTuple

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float32]
IntArray = NDArray[np.int64]

# Batched embedding output: shape (B, d), each row unit-norm float32.
Vectors = NDArray[np.float32]

# Element index table: shape (N, k) int32, one row for each image, -1
# pads a row with fewer than k elements (spec P3 section 7).
Incidence = NDArray[np.int32]

# One point of a stroke: floats in the unit square, (0, 0) top left,
# y down (spec P2 decision D2). Optional client fields (time, pressure)
# stay in the raw record and are not part of this type.
Point = tuple[float, float]

# One stroke: its points in input sequence.
StrokePath = tuple[Point, ...]

AtomType = Literal["DESCRIPTION", "RELATION", "WHOLE-DRAWING"]

ChannelName = str

# One number for each pool image: length N, ascending image_id.
PoolScores = NDArray[np.float32]

# Fusion weight table (spec P2 decision D12).
Weights = Mapping[ChannelName, float]

# The target's image_id. Enters the system in Layer 8 and nowhere before.
TargetId = str

# Length-N boolean array: 1 marks a decoy, 0 marks the target's full
# near-duplicate group (architecture section 16).
DecoySet = NDArray[np.bool_]

# The Layer 0 rejection causes (spec P2 section 10).
INTAKE_CAUSES: tuple[str, ...] = (
    "min-ink", "min-strokes", "text-length", "atom-count", "bad-shape")

# Routing table: atom type -> the built channels that read it (R14).
# Fusion derives the active channel set from this table, and the
# encode step reads it to select the atoms to encode — no code
# branches on modality (I5). RELATION atoms are read directly and are
# not encoded (architecture section 6).
ROUTING_TABLE: Mapping[AtomType, tuple[ChannelName, ...]] = {
    "DESCRIPTION": ("element",),
    "RELATION": ("placement",),
    "WHOLE-DRAWING": ("outline",),
}


class IntakeGates(NamedTuple):
    """The Layer 0 gate values (R3, decision D3), from ScoringConfig."""

    min_ink_pixels: int
    min_strokes_whole_drawing: int
    max_text_length: int
    max_atoms: int


class RenderParams(NamedTuple):
    """Canonical render values, read from the preparation config (R2)."""

    canvas_px: int
    line_width_px: int


class OutlineConfig(NamedTuple):
    """Outline channel configuration (decision D4)."""

    comparison_rule: str


class ElementConfig(NamedTuple):
    """Element channel configuration (spec P3 decisions D2, D3, D4, D10).

    epsilon and sinkhorn_iterations pin the soft matching. alpha is the
    text-to-sketch mixing knob of architecture section 6 and is 1.0 in
    this phase: the sketch-vector path behind lower values is not built.
    """

    comparison_rule: str
    matching_rule: str
    epsilon: float
    sinkhorn_iterations: int
    tier2_count: int
    alpha: float


class PlacementConfig(NamedTuple):
    """Placement channel configuration (spec P4 decision D4).

    relation_vocabulary names the relation strings scoring reads — a
    RELATION atom with a different string contributes nothing.
    area_cap keeps near-full-frame element boxes out of the locating
    rule: a box that covers the frame says nothing about placement.
    margin is the half-width of the axis-ramp-v1 soft check.
    """

    check_rule: str
    relation_vocabulary: tuple[str, ...]
    area_cap: float
    margin: float


@dataclass(frozen=True, slots=True)
class Atom:
    """One unit of a submission (architecture section 6).

    id is bookkeeping only — not encoded and not part of a score.
    subtype is recorded, not acted on, and is None in this phase: the
    frozen wire shape carries no subtype field (agreed 2026-08-08).
    refers_to and relation are filled on RELATION atoms only.
    """

    id: str
    type: AtomType
    subtype: str | None
    text: str | None
    strokes: tuple[StrokePath, ...] | None
    refers_to: tuple[str, str] | None
    relation: str | None


@dataclass(frozen=True, slots=True)
class Submission:
    """The atom set for one trial (architecture section 2)."""

    atoms: tuple[Atom, ...]


@dataclass(frozen=True, slots=True)
class EncodedSubmission:
    """Layer 2 output: the atom set plus vectors for routed atoms.

    vectors maps atom id to one unit-norm (d,) float32 row. Atoms with
    no built channel in ROUTING_TABLE have no entry.
    """

    atoms: tuple[Atom, ...]
    vectors: Mapping[str, FloatArray]


@dataclass(frozen=True, slots=True)
class PoolIndex:
    """The pool-side data that channels and ranking read (spec P2 §3).

    index_id is preparation_version_id for the plain pool, and the
    section 6 union formula for the V1 union index. image_ids is
    ascending with no repeats. outline_vectors has shape (N, 6, d), rows
    aligned with image_ids, second axis in the p06 row layout.
    outline_space_mean is the raw stored mean, not unit-norm.
    group_ids is aligned with image_ids and holds each image's p08
    near-duplicate group identifier.

    The element side comes from the p04 artifacts (spec P3 section 7).
    vocabulary holds B element strings and vocabulary_vectors their
    (B, d) unit-norm rows. pool_frequency holds the document frequency
    of the first V entries, which are the pool vocabulary itself, and
    pool_image_count is the image count of those frequencies. A
    V1 union index appends entries above V for photograph elements the
    pool does not name, and keeps the first V entries and
    pool_image_count as they are, so an atom's rarity weight stays
    pool-defined (spec P3 section 12). incidence indexes
    vocabulary_vectors for each image. element_space_mean is the raw
    stored mean of the pool vocabulary vectors, not unit-norm.

    The box side comes from the p07 artifacts (spec P4 section 7).
    box_table has shape (N, k, 4) with rows [x_min, y_min, x_max,
    y_max] in the unit square, slot-aligned with incidence, and
    box_mask (N, k) marks the slots that hold a box: the detector can
    decline an element, padding slots hold nothing, and a V1 union
    photograph holds no boxes at all. Masked-out slots hold zeros.
    """

    index_id: str
    image_ids: tuple[str, ...]
    outline_vectors: FloatArray
    outline_space_mean: FloatArray
    group_ids: tuple[str, ...]
    pool_image_count: int
    vocabulary: tuple[str, ...]
    pool_frequency: tuple[int, ...]
    vocabulary_vectors: FloatArray
    incidence: Incidence
    element_space_mean: FloatArray
    box_table: FloatArray
    box_mask: NDArray[np.bool_]


@dataclass(frozen=True, slots=True)
class ScoringContext:
    """The frozen parameter surface of one scoring configuration.

    Carries the pool index plus the configuration values score_trial
    reads: gates, render values, channel config, fusion weights, the
    commonness tables, and the identity hashes. commonness holds one
    table for each weighted channel the background submissions
    activate, which is a subset when the submission mode leaves a
    channel silent (spec P3 section 10). A trial that activates a
    channel with no table raises in score_trial.
    """

    index: PoolIndex
    gates: IntakeGates
    render: RenderParams
    outline: OutlineConfig
    element: ElementConfig
    placement: PlacementConfig
    weights: Weights
    commonness: Mapping[ChannelName, PoolScores]
    scoring_config_hash: str
    commonness_config_hash: str


@dataclass(frozen=True, slots=True)
class MatchRow:
    """One atom's correspondence with one image (spec P3 section 8.6).

    The architecture section 27 feedback shape: which element the atom
    matched, how much matched mass it holds (weight), the similarity of
    the pairing, and the atom's rarity weight in nats. element is None
    when the matched mass parks on the reserve bin, which says the atom
    matched nothing in that image.
    """

    atom_id: str
    atom_text: str
    element: str | None
    weight: float
    similarity: float
    rarity: float


@dataclass(frozen=True, slots=True)
class TrialScore:
    """The Layer 8 output (architecture section 16).

    p = (beaten + 0.5 * tied) / decoy_count. decoy_count is D, stored
    with each trial.
    """

    p: float
    decoy_count: int
    beaten: int
    tied: int
