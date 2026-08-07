"""Invariant 10: pool identity fixes preparation identity."""

from conftest import PREP_DEFAULT_SPECS, build_released_pool, make_prep_config, run_prep

from pool.preparation.stages.release import release_preparation_version_id

# The same pool but for the last image - a different membership.
_VARIANT_SPECS = PREP_DEFAULT_SPECS[:-1] + (
    (
        {"objects": ["silo", "barn", "tractor"], "setting": "outdoor farmyard"},
        "fam-d", "far", {},
    ),
)


def _run(root, specs):
    data = root / "data"
    releases = root / "releases"
    pool = build_released_pool(data, root / "pool-releases", specs)
    report = run_prep(make_prep_config(pool["record_path"]), data, releases)
    assert report.preparation_version_id is not None
    return pool, report


def test_different_membership_gives_different_identity(tmp_path):
    pool_a, report_a = _run(tmp_path / "a", PREP_DEFAULT_SPECS)
    pool_b, report_b = _run(tmp_path / "b", _VARIANT_SPECS)
    assert pool_a["pool_version_id"] != pool_b["pool_version_id"]
    assert report_a.preparation_version_id != report_b.preparation_version_id
    # With one shared preparation_config_hash the identities stay
    # different, because pool_version_id enters the identity hash
    # directly.
    shared_hash = "0" * 64
    assert release_preparation_version_id(
        pool_a["pool_version_id"], shared_hash
    ) != release_preparation_version_id(pool_b["pool_version_id"], shared_hash)


def test_same_pool_and_config_give_equal_identity(tmp_path):
    data = tmp_path / "data"
    releases = tmp_path / "releases"
    pool = build_released_pool(data, tmp_path / "pool-releases", PREP_DEFAULT_SPECS)
    config = make_prep_config(pool["record_path"])
    first = run_prep(config, data, releases)
    second = run_prep(config, data, releases)
    assert first.preparation_version_id is not None
    assert first.preparation_version_id == second.preparation_version_id
    assert first.release_label == second.release_label
    assert first.release_record_path == second.release_record_path
