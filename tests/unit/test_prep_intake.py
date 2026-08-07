"""Unit tests for the p00 intake rules: record parse and image checks."""

import hashlib
from io import BytesIO

import pytest
from PIL import Image

from pool.artifacts import ManifestError
from pool.preparation.stages.intake import (
    intake_check_membership,
    intake_check_release,
    intake_examine_image,
    intake_parse_release_record,
)
from pool.preparation.types import IntakeIssue, IntakeRecord


def _png_bytes(width: int = 5, height: int = 4) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _record_raw() -> dict:
    return {
        "label": "dev-wit-001-b89d8614",
        "pool_version_id": "ab" * 32,
        "corpus_id": "cd" * 32,
        "curation_config_hash": "ef" * 32,
        "corpus_identity": {"provider": "fake"},
        "config_path": "configs/curation/dev-wit.json",
        "image_count": 2,
        "funnel": {},
        "review": {"verdict": "pass"},
        "dev_only": True,
        "code_version": "abc123",
        "created_at": "2026-08-07T00:00:00+00:00",
    }


def test_valid_record_parses() -> None:
    record = intake_parse_release_record(_record_raw(), "test")
    assert record.label == "dev-wit-001-b89d8614"
    assert record.pool_version_id == "ab" * 32
    assert record.corpus_id == "cd" * 32
    assert record.curation_config_hash == "ef" * 32
    assert record.image_count == 2
    assert record.dev_only is True


def test_unknown_field_is_named() -> None:
    raw = _record_raw()
    raw["surprise"] = 1
    with pytest.raises(ManifestError, match="unknown field.*surprise"):
        intake_parse_release_record(raw, "test")


def test_missing_field_is_named() -> None:
    raw = _record_raw()
    del raw["funnel"]
    with pytest.raises(ManifestError, match="missing field.*funnel"):
        intake_parse_release_record(raw, "test")


def test_bad_hex_id_is_rejected() -> None:
    raw = _record_raw()
    raw["corpus_id"] = "XYZ"
    with pytest.raises(ManifestError, match=r"test\.corpus_id"):
        intake_parse_release_record(raw, "test")


def test_uppercase_hex_is_rejected() -> None:
    raw = _record_raw()
    raw["pool_version_id"] = "AB" * 32
    with pytest.raises(ManifestError, match=r"test\.pool_version_id"):
        intake_parse_release_record(raw, "test")


def test_image_count_zero_is_rejected() -> None:
    raw = _record_raw()
    raw["image_count"] = 0
    with pytest.raises(ManifestError, match=r"test\.image_count"):
        intake_parse_release_record(raw, "test")


def test_not_an_object_is_rejected() -> None:
    with pytest.raises(ManifestError, match="expected an object"):
        intake_parse_release_record([1, 2], "test")


def test_dev_only_mismatch_raises() -> None:
    record = intake_parse_release_record(_record_raw(), "test")
    with pytest.raises(ManifestError, match="R15"):
        intake_check_release(record, dev_only=False)


def test_dev_only_agreement_passes() -> None:
    record = intake_parse_release_record(_record_raw(), "test")
    intake_check_release(record, dev_only=True)


def test_membership_returns_sorted_ids() -> None:
    record = intake_parse_release_record(_record_raw(), "test")
    assert intake_check_membership(record, ["bb", "aa"]) == ("aa", "bb")


def test_membership_count_mismatch_raises() -> None:
    record = intake_parse_release_record(_record_raw(), "test")
    with pytest.raises(ManifestError, match="record says 2"):
        intake_check_membership(record, ["aa"])


def test_membership_duplicate_is_named() -> None:
    record = intake_parse_release_record(_record_raw(), "test")
    with pytest.raises(ManifestError, match="duplicated image_id.*aa"):
        intake_check_membership(record, ["aa", "aa"])


def test_examine_good_png_decodes_with_dims() -> None:
    image_bytes = _png_bytes(width=7, height=3)
    image_id = hashlib.sha256(image_bytes).hexdigest()
    outcome = intake_examine_image(image_id, image_bytes)
    assert isinstance(outcome, IntakeRecord)
    assert outcome.image_id == image_id
    assert outcome.width == 7
    assert outcome.height == 3
    assert outcome.image_format == "PNG"


def test_examine_hash_mismatch() -> None:
    image_bytes = _png_bytes()
    outcome = intake_examine_image("00" * 32, image_bytes)
    assert isinstance(outcome, IntakeIssue)
    assert outcome.kind == "hash-mismatch"
    assert outcome.detail == hashlib.sha256(image_bytes).hexdigest()


def test_examine_decode_error_detail_is_the_type_name_only() -> None:
    bad_bytes = b"not an image at all"
    image_id = hashlib.sha256(bad_bytes).hexdigest()
    outcome = intake_examine_image(image_id, bad_bytes)
    assert isinstance(outcome, IntakeIssue)
    assert outcome.kind == "decode-error"
    # One Python identifier only - no message, no memory address.
    assert outcome.detail.isidentifier()
    assert outcome.detail == "UnidentifiedImageError"
