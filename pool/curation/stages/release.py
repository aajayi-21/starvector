"""s09 release stage: pool version identity and the release label.

Spec: docs/specs/pool-curation.md section 6. Pure functions only -
the runner writes the release record and the manifest.
"""

from collections.abc import Sequence

from core.canonical import sha256_hex


def membership_hash(image_ids: Sequence[str]) -> str:
    """The inner hash of the pool membership.

    SHA-256 of the sorted image_id values, with one newline between
    them and none at the end. The input sequence has no effect on
    the result.
    """
    return sha256_hex("\n".join(sorted(image_ids)))


def pool_version_id(
    corpus_id: str, curation_config_hash: str, image_ids: Sequence[str]
) -> str:
    """The released pool identity (spec section 6).

    The hash input is the plain concatenation of corpus_id,
    curation_config_hash, and the membership hash - three lowercase
    hex strings, encoded as UTF-8.
    """
    return sha256_hex(corpus_id + curation_config_hash + membership_hash(image_ids))


def release_label(tag: str, pool_version: str) -> str:
    """The release name: the tag plus the first 8 hex digits of the id."""
    return f"{tag}-{pool_version[:8]}"
