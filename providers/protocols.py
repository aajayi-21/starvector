"""Capability protocols and boundary record types for all providers.

Spec: docs/specs/pool-curation.md sections 6, 7, and 8. Code in other
directories imports only these protocols, not a concrete provider.
Configuration selects the implementation at wiring time.
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import NamedTuple, Protocol

from core.types import FloatArray, Vectors


class CorpusIdentity(NamedTuple):
    """The tuple that pins one source corpus revision."""

    provider: str            # "huggingface" | "fake"
    repo_id: str             # "wikimedia/wit_base"
    revision: str            # resolved commit hash - not a branch name
    config_name: str | None  # datasets config, if one exists
    split: str               # "train"


class SourceRecord(NamedTuple):
    """One enumerated corpus record, before materialization."""

    source_key: str                 # stable in a pinned revision
    claimed_width: int | None       # from corpus metadata, can be missing
    claimed_height: int | None
    captions: tuple[str, ...]       # curation signal only (R10)
    attribution: Mapping[str, str]  # license and credit fields, passed through


class MaterializedImage(NamedTuple):
    """One retrieved image, with the retrieval provenance."""

    source_key: str
    image_bytes: bytes
    retrieval_note: str             # URL and parameters actually used


class MaterializeFailure(NamedTuple):
    """One explicit record-level failure (R14). Not a raised error."""

    source_key: str
    reason: str                     # "fetch-error" | "unsupported-media-type" | ...
    detail: str


class SourceCorpus(Protocol):
    """Source corpus access. Spec section 7.

    materialize_many results are index-aligned with the input records.
    The adapter owns chunking, concurrency, retries, and rate limits.
    """

    @property
    def identity(self) -> CorpusIdentity: ...

    @property
    def config_hash(self) -> str: ...

    @property
    def bytes_retrieved(self) -> int:
        """Monotone count of transport bytes this adapter retrieved (U1)."""
        ...

    def iter_records(self) -> Iterator[SourceRecord]: ...

    def materialize_many(
        self, records: Sequence[SourceRecord]
    ) -> list[MaterializedImage | MaterializeFailure]: ...


class ImageEncoder(Protocol):
    """Curation encoder slot for s06 and s07. Local only (U2)."""

    @property
    def config_hash(self) -> str: ...

    def encode_images(self, images: Sequence[bytes]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm."""
        ...


class ZeroShotImageClassifier(Protocol):
    """s04 slot. Probability values on a closed label set."""

    @property
    def config_hash(self) -> str: ...

    def classify(self, images: Sequence[bytes], labels: Sequence[str]) -> FloatArray:
        """The output is float32 (B, L) in label sequence. Each row sums to 1."""
        ...


class TextCoverageEstimator(Protocol):
    """s03 slot. Fraction of image area that text covers."""

    @property
    def config_hash(self) -> str: ...

    def estimate_text_coverage(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), each value in [0, 1]."""
        ...


class SalientObjectEstimator(Protocol):
    """s05 slot. Fraction of image area that the largest object covers."""

    @property
    def config_hash(self) -> str: ...

    def estimate_salient_object_fraction(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), each value in [0, 1]."""
        ...
