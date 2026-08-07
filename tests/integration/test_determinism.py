"""Invariants 3 and 6: byte-equal double run and byte-equal resume."""

import shutil

from conftest import (
    assert_trees_identical,
    find_stage_dir,
    make_config,
    run_pipeline,
    write_review,
)


def _full_run(root):
    data = root / "data"
    releases = root / "releases"
    config = make_config()
    run_pipeline(config, data, releases)
    write_review(data, "pass")
    report = run_pipeline(config, data, releases)
    assert report.halted_at is None
    return data, releases


def test_double_run_byte_identical(tmp_path):
    data_a, releases_a = _full_run(tmp_path / "a")
    data_b, releases_b = _full_run(tmp_path / "b")
    assert_trees_identical(data_a, data_b)
    assert_trees_identical(releases_a, releases_b)


def test_resume_from_s04_byte_identical(tmp_path):
    data, releases = _full_run(tmp_path / "run")
    reference = tmp_path / "reference"
    shutil.copytree(data, reference / "data")
    shutil.copytree(releases, reference / "releases")

    config = make_config()
    report = run_pipeline(config, data, releases, force_from="s04")
    # The gate opens again after s08 is rebuilt.
    assert report.halted_at == "s08-review"
    write_review(data, "pass")
    report = run_pipeline(config, data, releases)
    assert report.halted_at is None

    assert_trees_identical(data, reference / "data")
    assert_trees_identical(releases, reference / "releases")


def test_untouched_stages_are_not_recomputed(tmp_path):
    data, releases = _full_run(tmp_path / "run")
    s02_meta = find_stage_dir(data, "s02-materialize") / "meta.json"
    before = s02_meta.stat().st_mtime_ns
    config = make_config()
    run_pipeline(config, data, releases, force_from="s06")
    write_review(data, "pass")
    run_pipeline(config, data, releases)
    assert s02_meta.stat().st_mtime_ns == before
