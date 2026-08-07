"""Pure parts of stage s02: decode checks and the duplicate-bytes rule.

Spec: docs/specs/pool-curation.md section 10, s02. The runner fetches
and stores bytes. The functions here make decisions from in-memory
values only.
"""

from collections.abc import Sequence
from io import BytesIO
from typing import NamedTuple

from PIL import Image

from core.canonical import quantize_measured
from pool.curation.config import ScreenSection


class DecodedImage(NamedTuple):
    """The decoded pixel facts for one image."""

    width: int
    height: int
    image_format: str


class ScreenRejection(NamedTuple):
    """One s02 rejection cause, with the measured value when there is one."""

    reason: str
    measured: float | None
    detail: str


class DuplicateResolution(NamedTuple):
    """The output of the duplicate-bytes rule.

    kept rows are (source_key, image_id) pairs. rejected rows are
    (rejected_source_key, kept_source_key, image_id) triples.
    """

    kept: tuple[tuple[str, str], ...]
    rejected: tuple[tuple[str, str, str], ...]


def screen_decoded(
    image_bytes: bytes, screen: ScreenSection
) -> DecodedImage | ScreenRejection:
    """Decode one image and apply R2 and R3 to the decoded pixels.

    The decoded dimensions are authoritative - the claimed metadata is
    a hint. Bytes that do not decode as a raster image get the
    "decode-error" cause. This is how SVG and other vector files exit.
    R2 comes first, then R3, and the R3 range is inclusive.
    """
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            width, height = image.size
            image_format = image.format or "unknown"
    except Exception as error:
        # Pillow raises different error types for different bad files.
        # The error type only: Pillow messages can contain a memory
        # address, which breaks byte-for-byte determinism (spec 14).
        return ScreenRejection("decode-error", None, type(error).__name__)
    short_side = min(width, height)
    if short_side < screen.min_short_side:
        return ScreenRejection("resolution", float(short_side), "")
    aspect = width / height
    if aspect < screen.min_aspect or aspect > screen.max_aspect:
        return ScreenRejection("aspect", quantize_measured(aspect), "")
    return DecodedImage(width=width, height=height, image_format=image_format)


def resolve_duplicate_bytes(
    entries: Sequence[tuple[str, str]],
) -> DuplicateResolution:
    """Apply the duplicate-bytes rule to (source_key, image_id) pairs.

    When two or more source keys give the same bytes, the rule keeps
    the smallest source key and rejects each other source key against
    it. The function sorts the two output tuples. Thus the input
    sequence has no effect on the output.
    """
    by_image: dict[str, list[str]] = {}
    for source_key, image_id in entries:
        by_image.setdefault(image_id, []).append(source_key)
    kept: list[tuple[str, str]] = []
    rejected: list[tuple[str, str, str]] = []
    for image_id, source_keys in by_image.items():
        keeper = min(source_keys)
        kept.append((keeper, image_id))
        for source_key in source_keys:
            if source_key != keeper:
                rejected.append((source_key, keeper, image_id))
    return DuplicateResolution(kept=tuple(sorted(kept)), rejected=tuple(sorted(rejected)))
