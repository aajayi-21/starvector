"""Invariant 7: no s09 without a positive verdict from a human."""

import pytest

from conftest import find_stage_dir, make_config, run_pipeline, write_review

from pool.curation.manifest import ManifestError


def _no_stage_dir(data_root, stage):
    return not list(data_root.glob(f"curation/*/*/{stage}"))


def test_runner_refuses_s09_without_review(data_root, releases_root):
    config = make_config()
    report = run_pipeline(config, data_root, releases_root)
    assert report.halted_at == "s08-review"
    assert report.halt_reason == "awaiting-review"
    assert _no_stage_dir(data_root, "s09-release")
    assert not list(releases_root.glob("*.json"))


def test_runner_refuses_s09_on_fail_verdict(data_root, releases_root):
    config = make_config()
    run_pipeline(config, data_root, releases_root)
    write_review(data_root, "fail")
    report = run_pipeline(config, data_root, releases_root)
    assert report.halt_reason == "review-rejected"
    assert _no_stage_dir(data_root, "s09-release")


def test_runner_runs_s09_after_pass(data_root, releases_root):
    config = make_config()
    run_pipeline(config, data_root, releases_root)
    write_review(data_root, "pass")
    report = run_pipeline(config, data_root, releases_root)
    assert report.halted_at is None
    assert report.pool_version_id is not None
    assert report.release_label.startswith("dev-test-")


def test_malformed_review_json_raises(data_root, releases_root):
    config = make_config()
    run_pipeline(config, data_root, releases_root)
    path = find_stage_dir(data_root, "s08-review") / "review.json"
    path.write_text('{"verdict": "maybe", "reviewer": "x", "date": "y", "notes": ""}')
    with pytest.raises(ManifestError):
        run_pipeline(config, data_root, releases_root)
