"""The deferred boxes slot and its boundary (spec PP1 B8)."""

import json
from pathlib import Path

import pytest
from conftest import (build_prepared_pool_for_scoring, find_prep_stage_dir,
                      read_prep_stage_jsonl)

from pipeline.config import load_scoring_config
from providers.deferred_boxes import (DEFERRED_BOXES_HASH,
                                      DeferredElementBoxDetector)
from validation import harness

DEFERRED_SLOT = {"provider": "deferred", "model": None,
                 "instruction_template": None, "dimension": None}


def test_each_element_reads_as_not_located() -> None:
    answers = DeferredElementBoxDetector().detect_boxes(
        [b"a", b"b"], [["door", "wall"], ["sky"]])
    assert answers == [{"door": None, "wall": None}, {"sky": None}]


def test_a_placement_weight_is_refused_on_a_deferred_record() -> None:
    config = load_scoring_config(Path("configs/scoring/dev-wit-b-2.json"))
    assert "placement" in dict(config.fusion.weights)
    with pytest.raises(ValueError, match="deferred"):
        harness.check_boxes_prepared(config, {"element_boxes": DEFERRED_BOXES_HASH})
    harness.check_boxes_prepared(config, {"element_boxes": "a-real-box-hash"})


def test_no_placement_weight_clears_a_deferred_record() -> None:
    config = load_scoring_config(Path("configs/scoring/dev-wit-mixed-3.json"))
    assert "placement" not in dict(config.fusion.weights)
    harness.check_boxes_prepared(config, {"element_boxes": DEFERRED_BOXES_HASH})


def test_a_preparation_runs_with_deferred_boxes(tmp_path: Path) -> None:
    prepared = build_prepared_pool_for_scoring(
        tmp_path, **{"providers.element_boxes": DEFERRED_SLOT})
    data = prepared["data"]
    meta = json.loads((find_prep_stage_dir(data, "p07-boxes") / "meta.json").read_text())
    assert meta["provider_config_hashes"]["element_boxes"] == DEFERRED_BOXES_HASH
    assert meta["provider_posts"] == 0
    rows = read_prep_stage_jsonl(data, "p07-boxes", "boxes.jsonl")
    assert rows
    record = json.loads(prepared["prep_record_path"].read_text())
    assert record["provider_config_hashes"]["element_boxes"] == DEFERRED_BOXES_HASH
