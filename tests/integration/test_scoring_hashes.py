"""Invariant 9: config edits move the scoring-side artifact keys."""

from pathlib import Path

from conftest import make_scoring_config
from core.types import RenderParams
from pipeline.commonness import commonness_config_hash
from pipeline.config import scoring_config_hash
from validation.harness import harness_config_hash, scoring_provider_hashes

RECORD = Path("unused-record.json")
RENDER = RenderParams(canvas_px=512, line_width_px=3)


def _hashes(**overrides):
    config = make_scoring_config(RECORD, **overrides)
    slots = scoring_provider_hashes(config)
    scoring = scoring_config_hash(config, slots)
    commonness = commonness_config_hash(
        config, RENDER, slots["sketch_encoder"], slots["sketch_pairs"])
    return scoring, commonness


def test_the_split_salt_moves_the_two_hashes() -> None:
    base_scoring, base_commonness = _hashes()
    scoring, commonness = _hashes(**{"commonness.split_salt": "moved"})
    assert scoring != base_scoring
    assert commonness != base_commonness


def test_a_gate_moves_the_scoring_hash_and_not_the_table_key() -> None:
    base_scoring, base_commonness = _hashes()
    scoring, commonness = _hashes(**{"intake.min_ink_pixels": 50})
    assert scoring != base_scoring
    assert commonness == base_commonness


def test_the_weight_table_moves_the_scoring_hash() -> None:
    base_scoring, _ = _hashes()
    scoring, _ = _hashes(**{"fusion.weights": {"outline": 2.0}})
    assert scoring != base_scoring


def test_the_dataset_moves_the_two_hashes() -> None:
    base_scoring, base_commonness = _hashes()
    scoring, commonness = _hashes(
        **{"commonness.dataset.fake_pair_count": 32})
    assert scoring != base_scoring
    assert commonness != base_commonness


def test_the_harness_hash_keeps_the_two_harnesses_apart() -> None:
    base_scoring, _ = _hashes()
    assert harness_config_hash("v1", base_scoring) \
        != harness_config_hash("v2", base_scoring)


def test_the_encoder_dimension_moves_the_two_hashes() -> None:
    base_scoring, base_commonness = _hashes()
    scoring, commonness = _hashes(
        **{"providers.sketch_encoder.dimension": 64})
    assert scoring != base_scoring
    assert commonness != base_commonness
