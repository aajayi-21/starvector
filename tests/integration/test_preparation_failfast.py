"""Invariant 2 (R13): one bad image stops the run and writes nothing."""

import pytest

from conftest import PREP_DEFAULT_SPECS, build_released_pool, make_prep_config, run_prep

from pool.artifacts import image_path

_ERROR_TEXT = "scripted describer failure for the R13 check"


def _pool(tmp_path, specs):
    data = tmp_path / "data"
    pool = build_released_pool(data, tmp_path / "pool-releases", specs)
    return data, tmp_path / "releases", pool


def test_describer_error_stops_the_run_and_p01_stays_empty(tmp_path):
    specs = PREP_DEFAULT_SPECS[:2] + (
        ({}, None, None, {"fake_describer_error": _ERROR_TEXT}),
    )
    data, releases, pool = _pool(tmp_path, specs)
    config = make_prep_config(pool["record_path"])
    with pytest.raises(ValueError, match=_ERROR_TEXT):
        run_prep(config, data, releases)
    # p00 completed, thus one tree directory exists - but p01 wrote no
    # data file and no meta.
    tree_dirs = list(data.glob("preparation/*/*"))
    assert len(tree_dirs) == 1
    p01 = tree_dirs[0] / "p01-elements"
    assert not (p01 / "meta.json").exists()
    assert not (p01 / "elements.jsonl").exists()


def test_missing_image_bytes_stop_intake_with_the_image_named(tmp_path):
    data, releases, pool = _pool(tmp_path, PREP_DEFAULT_SPECS[:3])
    victim = pool["image_ids"][0]
    image_path(data, victim).unlink()
    config = make_prep_config(pool["record_path"])
    with pytest.raises(ValueError) as excinfo:
        run_prep(config, data, releases)
    message = str(excinfo.value)
    assert victim in message
    assert "missing-bytes" in message
    assert list(data.glob("preparation/**/meta.json")) == []


def test_corrupt_image_bytes_stop_intake_with_the_image_named(tmp_path):
    data, releases, pool = _pool(tmp_path, PREP_DEFAULT_SPECS[:3])
    victim = pool["image_ids"][1]
    image_path(data, victim).write_bytes(b"not the stored content")
    config = make_prep_config(pool["record_path"])
    with pytest.raises(ValueError) as excinfo:
        run_prep(config, data, releases)
    message = str(excinfo.value)
    assert victim in message
    assert "hash-mismatch" in message
    assert list(data.glob("preparation/**/meta.json")) == []
