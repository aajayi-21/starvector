"""Invariant 8: a config change moves the hash and the tree path."""

from pathlib import Path

from conftest import PREP_DEFAULT_SPECS, build_released_pool, make_prep_config, run_prep

from pool.preparation.config import preparation_config_hash
from pool.preparation.run import provider_config_hashes

# The hash is pure - these checks parse a config without a record file.
_UNUSED_RECORD = Path("unused-release-record.json")


def _hash_of(config):
    return preparation_config_hash(config, provider_config_hashes(config))


def test_neardup_threshold_change_makes_a_second_tree(tmp_path):
    data = tmp_path / "data"
    releases = tmp_path / "releases"
    pool = build_released_pool(data, tmp_path / "pool-releases", PREP_DEFAULT_SPECS)
    base = make_prep_config(pool["record_path"])
    first = run_prep(base, data, releases)
    changed = make_prep_config(
        pool["record_path"], **{"neardup.similarity_threshold": 0.9}
    )
    second = run_prep(changed, data, releases)
    assert second.preparation_config_hash != first.preparation_config_hash
    # The two trees sit side by side, keyed by the config hash.
    pool_dir = data / "preparation" / first.pool_version_id[:8]
    trees = sorted(path.name for path in pool_dir.iterdir())
    assert trees == sorted(
        {first.preparation_config_hash[:8], second.preparation_config_hash[:8]}
    )
    assert len(trees) == 2

    # An unchanged config comes back to the first tree and reruns nothing.
    again = run_prep(base, data, releases)
    assert again.preparation_config_hash == first.preparation_config_hash
    assert all(entry.skipped for entry in again.stages)
    assert sorted(path.name for path in pool_dir.iterdir()) == trees


def test_max_elements_change_moves_the_hash():
    base = make_prep_config(_UNUSED_RECORD)
    changed = make_prep_config(_UNUSED_RECORD, **{"elements.max_elements": 19})
    assert _hash_of(changed) != _hash_of(base)


def test_text_encoder_dimension_change_moves_the_hash_and_the_slot_hash():
    base = make_prep_config(_UNUSED_RECORD)
    changed = make_prep_config(
        _UNUSED_RECORD, **{"providers.text_encoder.dimension": 48}
    )
    assert _hash_of(changed) != _hash_of(base)
    # The slot hash itself moves too - it keys the encoder cache.
    assert (
        provider_config_hashes(changed)["text_encoder"]
        != provider_config_hashes(base)["text_encoder"]
    )
