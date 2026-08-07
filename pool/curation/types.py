"""Frozen record types for the pool curation pipeline.

Spec: docs/specs/pool-curation.md sections 3, 10, and 11. Each record is
immutable. Collections in records are tuples. Mapping-like fields are
sorted (key, value) pair tuples, so records hash and serialize
deterministically.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from core.canonical import JsonValue

STAGE_NAMES: tuple[str, ...] = (
    "s00-snapshot",
    "s01-screen",
    "s02-materialize",
    "s03-text",
    "s04-class",
    "s05-object",
    "s06-neardup",
    "s07-diversity",
    "s08-review",
    "s09-release",
)

# The vocabulary for the rejections file. The s04 value is dynamic:
# "class-<label>" with spaces in the label turned into hyphens.
REJECTION_REASONS: tuple[str, ...] = (
    "resolution-metadata",
    "aspect-metadata",
    "fetch-error",
    "fetch-too-large",
    "unsupported-media-type",
    "decode-error",
    "duplicate-bytes",
    "resolution",
    "aspect",
    "extraction-budget",
    "text-coverage",
    "object-size",
    "near-duplicate",
    "diversity-cap",
)

type PairTuple = tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class CandidateRecord:
    """One s00/s01 manifest row, before materialization."""

    source_key: str
    claimed_width: int | None
    claimed_height: int | None
    captions: tuple[str, ...]
    attribution: PairTuple


@dataclass(frozen=True, slots=True)
class ImageRecord:
    """One records.jsonl row, after materialization (s02 on)."""

    image_id: str          # sha256 hex of the stored bytes - primary key
    source_key: str
    width: int             # decoded, authoritative
    height: int
    image_format: str      # JSON key "format"
    captions: tuple[str, ...]
    attribution: PairTuple


@dataclass(frozen=True, slots=True)
class Rejection:
    """One rejections.jsonl row. Each removal is recorded with a cause."""

    key: str               # source_key through s02, image_id from s03 on
    stage: str             # a STAGE_NAMES value
    reason: str            # a REJECTION_REASONS entry or "class-<label>"
    measured: float | None  # the numeric value the rule examined
    detail: str


@dataclass(frozen=True, slots=True)
class StageResult[R]:
    """The output of one pure stage decision function."""

    survivors: tuple[R, ...]
    rejections: tuple[Rejection, ...]


@dataclass(frozen=True, slots=True)
class StageMeta:
    """meta.json content. Fully deterministic - timings live in timings.json."""

    stage: str
    label: str
    parent_stage: str | None
    input_count: int
    survivor_count: int
    rejection_count: int
    rejections_by_reason: tuple[tuple[str, int], ...]   # sorted
    config_echo: tuple[tuple[str, JsonValue], ...]      # this stage's config section
    provider_config_hashes: PairTuple                   # slots this stage used
    counters: tuple[tuple[str, int], ...]               # stage counters, sorted
    bytes_retrieved: int                                # by this stage (U1)
    bytes_cumulative: int                               # across stages so far (U1)
    provider_requests: int                              # POST or cache-miss count
    code_version: str                                   # git commit hash


@dataclass(frozen=True, slots=True)
class StageReport:
    """One stage entry of a RunReport."""

    stage: str
    label: str
    input_count: int
    survivor_count: int
    rejections_by_reason: tuple[tuple[str, int], ...]
    bytes_retrieved: int
    bytes_cumulative: int
    provider_requests: int
    skipped: bool          # set when resume reused a complete stage


@dataclass(frozen=True, slots=True)
class RunReport:
    """The output of run_curation. The contract a UI consumes."""

    corpus_id: str
    corpus_slug: str
    curation_config_hash: str
    stages: tuple[StageReport, ...]
    halted_at: str | None       # stage name when the run stopped there
    halt_reason: str | None     # awaiting-review or review-rejected
    pool_version_id: str | None  # set only when s09 ran
    release_label: str | None
    release_record_path: str | None


class ArtifactTree(NamedTuple):
    """The identity that addresses one artifact tree on disk."""

    data_root: Path
    corpus_id: str
    corpus_slug: str
    curation_config_hash: str


class ReviewRecord(NamedTuple):
    """The parsed review.json verdict for the s08 human gate."""

    verdict: str    # one of the two verdict literals
    reviewer: str
    date: str       # ISO 8601, human-entered
    notes: str
