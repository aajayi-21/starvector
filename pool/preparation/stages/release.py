"""p09 release rules: preparation version identity and record content.

Spec: docs/specs/pool-preparation.md sections 6 and 10, stage p09.
Pure functions only - the runner hashes the artifact files and writes
the committed record.
"""

from collections.abc import Mapping

from core.canonical import JsonValue, sha256_hex


def release_preparation_version_id(pool_version_id: str, preparation_config_hash: str) -> str:
    """The released preparation identity (spec section 6).

    The hash input is the plain concatenation of pool_version_id and
    preparation_config_hash - two lowercase hex strings, encoded as
    UTF-8. There is no membership hash: pool_version_id fixes the
    membership.
    """
    return sha256_hex(pool_version_id + preparation_config_hash)


def release_label(tag: str, preparation_version_id: str) -> str:
    """The release name: the tag plus the first 8 hex digits of the id."""
    return f"{tag}-{preparation_version_id[:8]}"


def release_record_content(
    *,
    label: str,
    preparation_version_id: str,
    pool_label: str,
    pool_version_id: str,
    pool_release_record_path: str,
    preparation_config_hash: str,
    config_path: str,
    image_count: int,
    artifacts: Mapping[str, str],
    provider_config_hashes: Mapping[str, str],
    provider_usage: Mapping[str, Mapping[str, int]],
    dev_only: bool,
    code_version: str,
    created_at: str,
) -> dict[str, JsonValue]:
    """The committed preparation record document (spec section 10, p09).

    artifacts maps the tree-relative path of each stage data file to
    the SHA-256 of its bytes - meta.json and timings.json are not in
    it, because meta content includes POST counts, which are
    different between a cold and a warm run. provider_usage carries
    the U1 counts for each slot.
    """
    return {
        "label": label,
        "preparation_version_id": preparation_version_id,
        "pool": {
            "label": pool_label,
            "pool_version_id": pool_version_id,
            "release_record_path": pool_release_record_path,
        },
        "preparation_config_hash": preparation_config_hash,
        "config_path": config_path,
        "image_count": image_count,
        "artifacts": {path: digest for path, digest in sorted(artifacts.items())},
        "provider_config_hashes": {
            slot: digest for slot, digest in sorted(provider_config_hashes.items())
        },
        "provider_usage": {
            slot: {"posts": int(usage["posts"]), "cache_hits": int(usage["cache_hits"])}
            for slot, usage in sorted(provider_usage.items())
        },
        "dev_only": dev_only,
        "code_version": code_version,
        "created_at": created_at,
    }
