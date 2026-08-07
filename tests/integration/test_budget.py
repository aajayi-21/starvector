"""Invariant 8: the extraction budget stops fetching with honest accounting."""

import json

from conftest import (
    DEFAULT_POPULATION,
    find_stage_dir,
    make_config,
    make_fake_corpus,
    read_stage_jsonl,
    run_pipeline,
)

from pool.curation.stages import snapshot


def _fetch_sizes(config):
    """Byte count of each fetch, in the deterministic fetch sequence."""
    corpus = make_fake_corpus()
    records = {r.source_key: r for r in corpus.iter_records()}
    # Screen as s01 does: claimed dims are the rule input.
    survivors = []
    for key, record in records.items():
        w, h = record.claimed_width, record.claimed_height
        if w is not None and h is not None:
            if min(w, h) < config.screen.min_short_side:
                continue
            aspect = w / h
            if not (config.screen.min_aspect <= aspect <= config.screen.max_aspect):
                continue
        survivors.append(key)
    order = snapshot.fetch_order(survivors, config.sampling.sample_salt)
    fresh = make_fake_corpus()
    sizes = []
    for key in order:
        (result,) = fresh.materialize_many([records[key]])
        sizes.append(len(result.image_bytes) if hasattr(result, "image_bytes") else 0)
    scan_bytes = 100 * sum(count for _, count in DEFAULT_POPULATION)
    return order, sizes, scan_bytes


def test_small_budget_stops_at_boundary(tmp_path):
    config = make_config()
    order, sizes, scan_bytes = _fetch_sizes(config)
    m = 5
    budget = scan_bytes + sum(sizes[:m])
    expected_fetched = len([s for s in sizes[:m] if s > 0])
    config = make_config(**{
        "extraction.budget_bytes": budget,
        "corpus.materialization.fetch_batch_size": 1,
    })
    data = tmp_path / "data"
    run_pipeline(config, data, tmp_path / "releases", through="s02")
    meta = json.loads((find_stage_dir(data, "s02-materialize") / "meta.json").read_text())
    assert meta["counters"]["fetched"] == expected_fetched
    assert meta["counters"]["budget_stopped"] == 1
    assert meta["counters"]["decision_bytes"] == budget


def test_unfetched_candidates_have_extraction_budget_cause(tmp_path):
    config = make_config()
    _, sizes, scan_bytes = _fetch_sizes(config)
    budget = scan_bytes + sum(sizes[:3])
    config = make_config(**{
        "extraction.budget_bytes": budget,
        "corpus.materialization.fetch_batch_size": 1,
    })
    data = tmp_path / "data"
    run_pipeline(config, data, tmp_path / "releases", through="s02")
    rejections = read_stage_jsonl(data, "s02-materialize", "rejections.jsonl")
    budget_rejections = [r for r in rejections if r["reason"] == "extraction-budget"]
    meta = json.loads((find_stage_dir(data, "s02-materialize") / "meta.json").read_text())
    s01_meta = json.loads((find_stage_dir(data, "s01-screen") / "meta.json").read_text())
    assert meta["input_count"] == s01_meta["survivor_count"]
    assert meta["input_count"] == meta["survivor_count"] + meta["rejection_count"]
    # Candidates split into: fetched images, attempted fetch failures,
    # and the unattempted remainder. The remainder equals the set of
    # extraction-budget rejections.
    fetch_failures = [r for r in rejections if r["reason"] == "fetch-error"]
    attempted = meta["counters"]["fetched"] + len(fetch_failures)
    assert len(budget_rejections) == meta["input_count"] - attempted
    assert budget_rejections, "budget truncation produced no rejections"


def test_materialize_cap_limits_fetch_count(tmp_path):
    config = make_config(**{
        "extraction.materialize_cap": 2,
        "corpus.materialization.fetch_batch_size": 1,
    })
    data = tmp_path / "data"
    run_pipeline(config, data, tmp_path / "releases", through="s02")
    meta = json.loads((find_stage_dir(data, "s02-materialize") / "meta.json").read_text())
    assert meta["counters"]["fetched"] == 2
