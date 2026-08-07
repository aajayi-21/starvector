"""Unit tests for the s00 sampling rules in pool.curation.stages.snapshot."""

import hashlib
import random

from pool.curation.stages.snapshot import fetch_order, keep_in_sample, sampling_hash


def _reference_hash(sample_salt: str, source_key: str) -> int:
    digest = hashlib.sha256((sample_salt + source_key).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def test_sampling_hash_agrees_with_the_reference_formula() -> None:
    assert sampling_hash("salt", "key") == _reference_hash("salt", "key")


def test_sampling_hash_agrees_on_more_inputs() -> None:
    for sample_salt, source_key in [("", "a"), ("s1", "k1"), ("sel-é", "clé-ü")]:
        assert sampling_hash(sample_salt, source_key) == _reference_hash(
            sample_salt, source_key
        )


def test_kept_set_does_not_depend_on_enumeration_sequence() -> None:
    keys = [f"key-{i:03d}" for i in range(200)]
    shuffled = keys.copy()
    random.Random(7).shuffle(shuffled)
    assert shuffled != keys
    kept_sorted = {k for k in keys if keep_in_sample("salt", k, 0.5)}
    kept_shuffled = {k for k in shuffled if keep_in_sample("salt", k, 0.5)}
    assert kept_sorted == kept_shuffled
    assert 0 < len(kept_sorted) < len(keys)


def test_rate_one_keeps_all() -> None:
    keys = [f"key-{i}" for i in range(50)]
    assert all(keep_in_sample("salt", k, 1.0) for k in keys)


def test_rate_just_above_zero_keeps_none() -> None:
    keys = ["alpha", "beta", "gamma", "delta", "epsilon"]
    assert not any(keep_in_sample("salt", k, 1e-12) for k in keys)


def test_fetch_order_sorts_by_hash_then_key() -> None:
    keys = [f"key-{i:02d}" for i in range(20)]
    expected = tuple(sorted(keys, key=lambda k: (_reference_hash("salt", k), k)))
    assert fetch_order(keys, "salt") == expected
    assert fetch_order(reversed(keys), "salt") == expected
    # The hash sequence differs from the plain key sequence.
    assert expected != tuple(keys)
