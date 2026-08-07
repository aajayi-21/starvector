"""Frozen record types for the pool preparation pipeline.

Spec: docs/specs/pool-preparation.md sections 3, 10, and 11. Each record
is immutable. Collections in records are tuples. Mapping-like fields are
sorted (key, value) pair tuples, so records hash and serialize
deterministically. ElementResponse and Box live in
providers/protocols.py - the parse boundary owns them - and are
re-exported here.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from core.canonical import JsonValue
from providers.protocols import Box, ElementResponse

__all__ = [
    "Box",
    "CutRecord",
    "ELEMENT_FIELDS",
    "ElementResponse",
    "GroupRow",
    "INTAKE_ISSUE_KINDS",
    "IntakeIssue",
    "IntakeRecord",
    "PoolReleaseRecord",
    "PreparationReport",
    "PreparationTree",
    "ReleaseFacts",
    "STAGE_NAMES",
    "StageMeta",
    "StageReport",
]

STAGE_NAMES: tuple[str, ...] = (
    "p00-intake",
    "p01-elements",
    "p02-normalize",
    "p03-cap",
    "p04-vocabulary",
    "p05-linedraw",
    "p06-outline",
    "p07-boxes",
    "p08-neardup",
    "p09-release",
)

# The flatten sequence of decision D8: the R2 schema fields in the
# sequence in which their entries become the element list.
ELEMENT_FIELDS: tuple[str, ...] = (
    "objects",
    "materials",
    "colors",
    "shapes",
    "scale",
    "setting",
    "ambience",
)

INTAKE_ISSUE_KINDS: tuple[str, ...] = ("missing-bytes", "hash-mismatch", "decode-error")

type PairTuple = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PoolReleaseRecord:
    """The parsed P1a release record - the p00 input contract."""

    label: str
    pool_version_id: str
    corpus_id: str
    curation_config_hash: str
    image_count: int
    dev_only: bool


@dataclass(frozen=True, slots=True)
class IntakeRecord:
    """One p00 records.jsonl row: decoded pixel facts for one image."""

    image_id: str
    width: int
    height: int
    image_format: str      # JSON key "format"


@dataclass(frozen=True, slots=True)
class IntakeIssue:
    """One p00 problem. An issue stops the run - R13 permits no skip."""

    image_id: str
    kind: str              # an INTAKE_ISSUE_KINDS value
    detail: str


@dataclass(frozen=True, slots=True)
class CutRecord:
    """One p03 cuts.jsonl row: an entry the R3 cap removed."""

    image_id: str
    element: str
    df: int                    # count of images with the element (p02)
    capping_rarity: float      # negative natural logarithm of df / N, quantized


@dataclass(frozen=True, slots=True)
class GroupRow:
    """One p08 groups.jsonl row. Layer 8 reads this table (R10)."""

    image_id: str
    group_id: str          # smallest member image_id of the component
    member_count: int


@dataclass(frozen=True, slots=True)
class StageMeta:
    """meta.json content. Fully deterministic - timings live in timings.json."""

    stage: str
    label: str
    parent_stage: str | None
    image_count: int
    config_echo: tuple[tuple[str, JsonValue], ...]      # this stage's config section
    provider_config_hashes: PairTuple                   # slots this stage used
    counters: tuple[tuple[str, int], ...]               # stage counters, sorted
    array_shapes: tuple[tuple[str, tuple[int, ...]], ...]  # .npy shapes, sorted
    provider_posts: int                                 # U1 POST count
    provider_cache_hits: int                            # U1 cache-hit count
    code_version: str                                   # git commit hash


@dataclass(frozen=True, slots=True)
class StageReport:
    """One stage entry of a PreparationReport."""

    stage: str
    label: str
    image_count: int
    provider_posts: int
    provider_cache_hits: int
    counters: tuple[tuple[str, int], ...]
    skipped: bool          # set when resume reused a complete stage


@dataclass(frozen=True, slots=True)
class PreparationReport:
    """The output of run_preparation. The contract a UI consumes."""

    pool_version_id: str
    pool_label: str
    preparation_config_hash: str
    stages: tuple[StageReport, ...]
    preparation_version_id: str | None  # set only when p09 ran
    release_label: str | None
    release_record_path: str | None


class PreparationTree(NamedTuple):
    """The identity that addresses one preparation artifact tree on disk."""

    data_root: Path
    pool_version_id: str
    preparation_config_hash: str
    pool_label: str


class ReleaseFacts(NamedTuple):
    """The p09 output facts that enter the PreparationReport."""

    preparation_version_id: str
    release_label: str
    record_path: Path
