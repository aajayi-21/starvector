"""Unit tests for the p09 identity and record content rules."""

import hashlib

from pool.preparation.stages.release import (
    release_label,
    release_preparation_version_id,
    release_record_content,
)


def test_version_id_against_a_hashlib_reference() -> None:
    pool_version = "11" * 32
    config_hash = "22" * 32
    expected = hashlib.sha256((pool_version + config_hash).encode("utf-8")).hexdigest()
    assert release_preparation_version_id(pool_version, config_hash) == expected


def test_version_id_is_sensitive_to_each_component() -> None:
    base = release_preparation_version_id("11" * 32, "22" * 32)
    assert base != release_preparation_version_id("33" * 32, "22" * 32)
    assert base != release_preparation_version_id("11" * 32, "44" * 32)


def test_release_label() -> None:
    version = "abcdef0123456789" * 4
    assert release_label("dev-prep-001", version) == "dev-prep-001-abcdef01"


def _content() -> dict:
    return release_record_content(
        label="dev-prep-001-abcdef01",
        preparation_version_id="ab" * 32,
        pool_label="dev-wit-001-b89d8614",
        pool_version_id="cd" * 32,
        pool_release_record_path="pool/releases/dev-wit-001-b89d8614.json",
        preparation_config_hash="ef" * 32,
        config_path="configs/preparation/dev-wit.json",
        image_count=225,
        artifacts={"p00-intake/records.jsonl": "00" * 32},
        provider_config_hashes={"describer": "11" * 32},
        provider_usage={"describer": {"posts": 3, "cache_hits": 7}},
        dev_only=True,
        code_version="abc123",
        created_at="2026-08-07T00:00:00+00:00",
    )


def test_record_key_set_is_pinned() -> None:
    content = _content()
    assert set(content) == {
        "label",
        "preparation_version_id",
        "pool",
        "preparation_config_hash",
        "config_path",
        "image_count",
        "artifacts",
        "provider_config_hashes",
        "provider_usage",
        "dev_only",
        "code_version",
        "created_at",
    }
    assert set(content["pool"]) == {"label", "pool_version_id", "release_record_path"}


def test_record_carries_the_pool_reference_and_usage() -> None:
    content = _content()
    assert content["pool"]["label"] == "dev-wit-001-b89d8614"
    assert content["pool"]["pool_version_id"] == "cd" * 32
    assert content["provider_usage"] == {"describer": {"posts": 3, "cache_hits": 7}}
    assert content["artifacts"] == {"p00-intake/records.jsonl": "00" * 32}
    assert content["dev_only"] is True
