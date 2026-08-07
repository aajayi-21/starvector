"""Stage p00 intake rules. Pure parsing and image checks.

Spec: docs/specs/pool-preparation.md sections 7 and 10, stage p00. The
release record and the image store are the full interface between
curation and preparation. The runner does all reads - the functions
here work on in-memory values.
"""

import re
from collections import Counter
from collections.abc import Sequence
from io import BytesIO

from PIL import Image

from core.canonical import sha256_hex
from pool.artifacts import ManifestError
from pool.preparation.types import IntakeIssue, IntakeRecord, PoolReleaseRecord

# The full field set of a P1a s09 release record. Preparation uses six
# fields and discards the six others without a look at their content.
_USED_FIELDS: tuple[str, ...] = (
    "label",
    "pool_version_id",
    "corpus_id",
    "curation_config_hash",
    "image_count",
    "dev_only",
)
_DISCARDED_FIELDS: tuple[str, ...] = (
    "corpus_identity",
    "config_path",
    "funnel",
    "review",
    "code_version",
    "created_at",
)

_HEX64 = re.compile(r"[0-9a-f]{64}")


def intake_parse_release_record(raw: object, source: str) -> PoolReleaseRecord:
    """Strict parse of one curation release record document.

    The twelve known top-level fields are checked. An unknown or
    missing field raises ManifestError with the field named (R14). The
    three identity fields must be 64 lowercase hex digits, and
    image_count must be 1 or more. The six fields preparation does
    not use are consumed and discarded - the record and the image
    store are the full curation interface (spec section 7).
    """
    if not isinstance(raw, dict):
        raise ManifestError(f"{source}: expected an object")
    fields = dict(raw)
    known = set(_USED_FIELDS) | set(_DISCARDED_FIELDS)
    unknown = set(fields) - known
    if unknown:
        raise ManifestError(f"{source}: unknown field(s): {sorted(unknown)}")
    missing = known - set(fields)
    if missing:
        raise ManifestError(f"{source}: missing field(s): {sorted(missing)}")
    label = fields["label"]
    if not isinstance(label, str) or not label:
        raise ManifestError(f"{source}.label: expected a non-empty string")
    for key in ("pool_version_id", "corpus_id", "curation_config_hash"):
        value = fields[key]
        if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
            raise ManifestError(f"{source}.{key}: expected 64 lowercase hex digits")
    image_count = fields["image_count"]
    if not isinstance(image_count, int) or isinstance(image_count, bool) or image_count < 1:
        raise ManifestError(f"{source}.image_count: expected an integer of at least 1")
    dev_only = fields["dev_only"]
    if not isinstance(dev_only, bool):
        raise ManifestError(f"{source}.dev_only: expected a boolean")
    return PoolReleaseRecord(
        label=label,
        pool_version_id=fields["pool_version_id"],
        corpus_id=fields["corpus_id"],
        curation_config_hash=fields["curation_config_hash"],
        image_count=image_count,
        dev_only=dev_only,
    )


def intake_check_release(record: PoolReleaseRecord, dev_only: bool) -> None:
    """The R15 equality check between the pool release and the config.

    When the record and the config do not agree on dev_only, this
    check raises ManifestError before an artifact tree exists.
    """
    if record.dev_only != dev_only:
        raise ManifestError(
            f"release {record.label}: dev_only is {record.dev_only} but the "
            f"preparation config says {dev_only} (R15)"
        )


def intake_check_membership(
    record: PoolReleaseRecord, manifest_ids: Sequence[str]
) -> tuple[str, ...]:
    """Reconcile the s09 manifest with the release record (spec section 7).

    The image_id count must equal record.image_count and the
    identifiers must be unique. The output is the sorted membership.
    A mismatch raises ManifestError with the problem named (R13).
    """
    counts = Counter(manifest_ids)
    duplicated = sorted(image_id for image_id, count in counts.items() if count > 1)
    if duplicated:
        raise ManifestError(
            f"release {record.label}: duplicated image_id(s) in the manifest: {duplicated}"
        )
    if len(counts) != record.image_count:
        raise ManifestError(
            f"release {record.label}: manifest has {len(counts)} image(s) but the "
            f"record says {record.image_count}"
        )
    return tuple(sorted(counts))


def intake_examine_image(image_id: str, image_bytes: bytes) -> IntakeRecord | IntakeIssue:
    """Check one image's stored bytes and decode its pixel facts.

    Bytes with a SHA-256 digest different from image_id give a
    "hash-mismatch" issue that carries the measured digest. Bytes
    that do not decode give a "decode-error" issue that carries the
    error type name, and nothing more - Pillow messages can contain a
    memory address, which breaks byte-for-byte determinism (spec
    section 14).
    """
    measured = sha256_hex(image_bytes)
    if measured != image_id:
        return IntakeIssue(image_id=image_id, kind="hash-mismatch", detail=measured)
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.load()
            width, height = image.size
            image_format = image.format or "unknown"
    except Exception as error:
        return IntakeIssue(image_id=image_id, kind="decode-error", detail=type(error).__name__)
    return IntakeRecord(image_id=image_id, width=width, height=height, image_format=image_format)
