"""Unit tests for the s09 pure functions: identity hashes and label."""

import hashlib
import random

from pool.curation.stages.release import membership_hash, pool_version_id, release_label


def test_membership_hash_matches_the_pinned_reference() -> None:
    expected = hashlib.sha256(b"a\nb").hexdigest()
    assert membership_hash(["b", "a"]) == expected


def test_membership_hash_has_no_trailing_newline() -> None:
    with_trailing = hashlib.sha256(b"a\nb\n").hexdigest()
    assert membership_hash(["b", "a"]) != with_trailing


def test_pool_version_id_matches_the_pinned_construction() -> None:
    inner = hashlib.sha256(b"a\nb").hexdigest()
    expected = hashlib.sha256(("corpus" + "config" + inner).encode("utf-8")).hexdigest()
    assert pool_version_id("corpus", "config", ["b", "a"]) == expected


def test_pool_version_id_changes_with_corpus_id() -> None:
    ids = ["a", "b"]
    assert pool_version_id("corpus-one", "conf", ids) != pool_version_id(
        "corpus-two", "conf", ids
    )


def test_pool_version_id_changes_with_config_hash() -> None:
    ids = ["a", "b"]
    assert pool_version_id("corpus", "conf-one", ids) != pool_version_id(
        "corpus", "conf-two", ids
    )


def test_pool_version_id_ignores_the_input_sequence() -> None:
    ids = [f"{index:064x}" for index in range(20)]
    shuffled = ids.copy()
    random.Random(5).shuffle(shuffled)
    assert shuffled != ids
    assert pool_version_id("c", "h", shuffled) == pool_version_id("c", "h", ids)


def test_release_label_format() -> None:
    version = "0123456789abcdef" * 4
    assert release_label("dev-wit-001", version) == "dev-wit-001-01234567"
