"""Invariants 7 and 9: byte-equal double run and byte-equal resume."""

import shutil
from pathlib import Path

from conftest import (
    PREP_DEFAULT_SPECS,
    assert_trees_identical,
    build_released_pool,
    find_prep_stage_dir,
    make_prep_config,
    run_prep,
)

from pool.preparation.types import STAGE_NAMES


def _run_with_relative_record(root, monkeypatch):
    # A relative record path keeps the config document equal between
    # the two roots, and thus keeps the tree paths equal.
    monkeypatch.chdir(root)
    data = root / "data"
    releases = root / "releases"
    pool = build_released_pool(data, Path("pool-releases"), PREP_DEFAULT_SPECS)
    report = run_prep(make_prep_config(pool["record_path"]), data, releases)
    assert report.preparation_version_id is not None
    return data, releases


def _full_run(root):
    data = root / "data"
    releases = root / "releases"
    pool = build_released_pool(data, root / "pool-releases", PREP_DEFAULT_SPECS)
    config = make_prep_config(pool["record_path"])
    report = run_prep(config, data, releases)
    assert report.preparation_version_id is not None
    return data, releases, config


def test_double_run_byte_identical(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    data_a, releases_a = _run_with_relative_record(tmp_path / "a", monkeypatch)
    data_b, releases_b = _run_with_relative_record(tmp_path / "b", monkeypatch)
    assert_trees_identical(data_a, data_b)
    assert_trees_identical(releases_a, releases_b)


def test_resume_from_p04_byte_identical(tmp_path):
    data, releases, config = _full_run(tmp_path / "run")
    reference = tmp_path / "reference"
    shutil.copytree(data, reference / "data")
    shutil.copytree(releases, reference / "releases")
    mtimes_before = {
        stage: (find_prep_stage_dir(data, stage) / "meta.json").stat().st_mtime_ns
        for stage in STAGE_NAMES[:4]
    }

    report = run_prep(config, data, releases, force_from="p04")
    assert [entry.skipped for entry in report.stages] == [True] * 4 + [False] * 6

    # Byte-for-byte, metas included: meta.json holds no value that
    # changes with local cache warmth (spec section 15, invariant 9).
    assert_trees_identical(data, reference / "data")
    assert_trees_identical(releases, reference / "releases")
    # p00 through p03 stayed untouched on disk.
    for stage, before in mtimes_before.items():
        path = find_prep_stage_dir(data, stage) / "meta.json"
        assert path.stat().st_mtime_ns == before, stage


def test_second_resume_byte_identical_with_the_metas(tmp_path):
    data, releases, config = _full_run(tmp_path / "run")
    run_prep(config, data, releases, force_from="p04")
    reference = tmp_path / "reference"
    shutil.copytree(data, reference / "data")
    shutil.copytree(releases, reference / "releases")
    run_prep(config, data, releases, force_from="p04")
    # Warm against warm: the full trees agree, metas included.
    assert_trees_identical(data, reference / "data")
    assert_trees_identical(releases, reference / "releases")


def test_plain_rerun_skips_each_stage(completed_preparation):
    data = completed_preparation["data"]
    meta_paths = {
        stage: find_prep_stage_dir(data, stage) / "meta.json"
        for stage in STAGE_NAMES[:4]
    }
    before = {stage: path.stat().st_mtime_ns for stage, path in meta_paths.items()}
    report = run_prep(
        completed_preparation["config"], data, completed_preparation["releases"]
    )
    assert len(report.stages) == len(STAGE_NAMES)
    assert all(entry.skipped for entry in report.stages)
    first_report = completed_preparation["report"]
    assert report.preparation_version_id == first_report.preparation_version_id
    for stage, path in meta_paths.items():
        assert path.stat().st_mtime_ns == before[stage], stage
