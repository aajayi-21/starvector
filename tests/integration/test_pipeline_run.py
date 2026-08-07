"""End-to-end fake run: artifact tree, subset chain, accounting."""

import json

from conftest import find_stage_dir, read_stage_jsonl

from pool.curation.types import STAGE_NAMES


def test_full_fake_run_creates_complete_artifact_tree(completed_run):
    data = completed_run["data"]
    for stage in STAGE_NAMES:
        directory = find_stage_dir(data, stage)
        assert (directory / "manifest.jsonl").exists(), stage
        assert (directory / "meta.json").exists(), stage
    assert (find_stage_dir(data, "s02-materialize") / "records.jsonl").exists()
    s08 = find_stage_dir(data, "s08-review")
    assert (s08 / "sample.jsonl").exists()
    assert (s08 / "contact_sheet.html").exists()
    report = completed_run["report"]
    releases = completed_run["releases"]
    record_path = releases / f"{report.release_label}.json"
    assert record_path.exists()
    record = json.loads(record_path.read_text())
    assert record["dev_only"] is True
    assert record["pool_version_id"] == report.pool_version_id
    assert record["image_count"] > 0
    assert set(record["funnel"]) == set(STAGE_NAMES[:-1])


def test_subset_chain_across_stages(completed_run):
    data = completed_run["data"]
    previous_keys = None
    for stage in STAGE_NAMES:
        rows = read_stage_jsonl(data, stage, "manifest.jsonl")
        key = "image_id" if stage >= "s02" else "source_key"
        keys = {row[key] for row in rows}
        if previous_keys is not None and stage != "s02-materialize":
            assert keys <= previous_keys, f"{stage} is not a subset of its parent"
        previous_keys = keys


def test_accounting_per_stage(completed_run):
    data = completed_run["data"]
    parent_count = None
    for stage in STAGE_NAMES:
        manifest = read_stage_jsonl(data, stage, "manifest.jsonl")
        rejections_path = find_stage_dir(data, stage) / "rejections.jsonl"
        rejections = (
            read_stage_jsonl(data, stage, "rejections.jsonl")
            if rejections_path.exists()
            else []
        )
        meta = json.loads((find_stage_dir(data, stage) / "meta.json").read_text())
        assert meta["input_count"] == meta["survivor_count"] + meta["rejection_count"], stage
        assert meta["survivor_count"] == len(manifest), stage
        assert meta["rejection_count"] == len(rejections), stage
        for row in rejections:
            assert row["reason"], f"{stage}: rejection without a reason"
        if parent_count is not None:
            assert meta["input_count"] == parent_count, stage
        parent_count = meta["survivor_count"]


def test_funnel_report_numbers_match_meta(completed_run):
    data = completed_run["data"]
    report = completed_run["report"]
    for entry in report.stages:
        meta = json.loads((find_stage_dir(data, entry.stage) / "meta.json").read_text())
        assert entry.input_count == meta["input_count"]
        assert entry.survivor_count == meta["survivor_count"]
        assert dict(entry.rejections_by_reason) == meta["rejections_by_reason"]
        assert entry.bytes_cumulative == meta["bytes_cumulative"]


def test_every_planned_rejection_reason_appears(completed_run):
    data = completed_run["data"]
    seen = set()
    for stage in STAGE_NAMES:
        path = find_stage_dir(data, stage) / "rejections.jsonl"
        if path.exists():
            seen |= {row["reason"] for row in read_stage_jsonl(data, stage, "rejections.jsonl")}
    expected = {
        "resolution-metadata",
        "aspect-metadata",
        "fetch-error",
        "decode-error",
        "duplicate-bytes",
        "resolution",
        "text-coverage",
        "object-size",
        "near-duplicate",
        "diversity-cap",
        "class-diagram",
        "class-logo",
        "class-map",
    }
    assert expected <= seen, f"missing rejection reasons: {expected - seen}"
