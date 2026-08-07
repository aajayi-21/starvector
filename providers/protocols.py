"""Capability protocols and boundary record types for all providers.

Spec: docs/specs/pool-curation.md sections 6, 7, and 8, plus
docs/specs/pool-preparation.md section 8. Code in other directories
imports only these protocols, not a concrete provider. Configuration
selects the implementation at wiring time.
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
    """Image encoder slot: curation s06 and s07, preparation p06.

    Each pipeline wires its own instance with its own config hash
    (CLAUDE.md section 6). Implementations: local, OpenRouter
    embeddings, or fake.
    """

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


class Box(NamedTuple):
    """One element box, each value normalized to [0, 1]."""

    x_min: float
    y_min: float
    x_max: float
    y_max: float


class ElementResponse(NamedTuple):
    """The fixed element structure of ARCHITECTURE.md section 5 (R2).

    Field sequence is the flatten sequence of spec P1b decision D8.
    The fifth and sixth fields are plain strings, not one-entry
    tuples - that is the shape the architecture's example gives.
    """

    objects: tuple[str, ...]
    materials: tuple[str, ...]
    colors: tuple[str, ...]
    shapes: tuple[str, ...]
    scale: str
    setting: str
    ambience: tuple[str, ...]


class VlmDescriber(Protocol):
    """p01 slot. One parsed element response for each image.

    The provider parses and validates at its boundary (R14): a response
    that does not parse, an empty field, or a field count not in the
    configured limits raises with the image hash named. Results are
    index-aligned with the input.
    """

    @property
    def config_hash(self) -> str: ...

    def describe_images(self, images: Sequence[bytes]) -> Sequence[ElementResponse]: ...


class TextEncoder(Protocol):
    """p04 slot. Batched text embedding.

    Implementations: OpenRouter embeddings, local, or fake.
    """

    @property
    def config_hash(self) -> str: ...

    def encode_texts(self, texts: Sequence[str]) -> Vectors:
        """The output is float32 (B, d), each row unit-norm."""
        ...


class LineDrawer(Protocol):
    """p05 slot. Photo to canonical line drawing. Local only (U2).

    Model inference, binarize, short-segment removal, and the canonical
    re-render are all internal to the provider (R7). Results are
    index-aligned with the input.
    """

    @property
    def config_hash(self) -> str: ...

    def draw_lines(self, images: Sequence[bytes]) -> Sequence[bytes]:
        """The output rows are canonical rendered line-drawing PNG bytes."""
        ...


class ElementBoxDetector(Protocol):
    """p07 slot. One box or None for each queried element of each image.

    element_lists is index-aligned with images. The response cache key
    covers the queried element list (spec P1b decision D10). A box out
    of range raises. None records "not located" and is a permitted
    answer, not an error.
    """

    @property
    def config_hash(self) -> str: ...

    def detect_boxes(
        self, images: Sequence[bytes], element_lists: Sequence[Sequence[str]]
    ) -> Sequence[Mapping[str, Box | None]]: ...
