"""The bench tool smoke: the record builds at toy count, offline.

The bench itself is a deliberate owner run (P5 R6), not a CI gate -
this keeps the tool importable and its record shape pinned.
"""

import json

from tools.bench import build_synthetic_index, main, run_bench


def test_the_record_holds_the_stage_numbers() -> None:
    record = run_bench(count=16, dimension=8, vocabulary_count=40,
                       seed=1, repeat=1,
                       clock=lambda: "2026-08-13T00:00:00+00:00")
    assert record["count"] == 16
    assert record["budget_ms"] == 50.0
    assert record["vectors"] == "synthetic"
    assert record["created_at"] == "2026-08-13T00:00:00+00:00"
    stages = {"render", "similarity_table", "tier1", "tier2",
              "element_total", "outline", "normalize", "fuse", "rank",
              "local_total"}
    assert stages == set(record["stage_ms"])
    assert all(value >= 0.0 for value in record["stage_ms"].values())
    assert record["resident_bytes"] > 0
    assert "cpu" in record["machine"]


def test_the_synthetic_index_is_scoreable() -> None:
    index = build_synthetic_index(count=12, dimension=8,
                                  vocabulary_count=30, seed=2)
    assert len(index.image_ids) == 12
    assert index.outline_centered is not None
    assert all(value >= 1 for value in index.pool_frequency)


def test_write_lands_the_record(tmp_path) -> None:
    code = main(["--count", "12", "--dimension", "8", "--vocabulary",
                 "30", "--repeat", "1", "--write",
                 "--records-root", str(tmp_path)])
    assert code == 0
    written = list(tmp_path.glob("bench-12-*.json"))
    assert len(written) == 1
    record = json.loads(written[0].read_text())
    assert record["tool"] == "bench"
