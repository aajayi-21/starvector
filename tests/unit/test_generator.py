"""Unit tests for the synthetic submission generator (spec P4 §8)."""

import numpy as np
import pytest

from core.canonical import canonical_json
from core.intake import validate_submission
from core.types import IntakeGates, PlacementConfig
from validation.fitconfig import parse_fit_config
from validation.generator import (generator_config_hash, relation_between,
                                  synthetic_set, synthetic_submission)
from tests.conftest import make_pool_index

DIMENSION = 8
COUNT = 6
IDS = tuple(chr(97 + position) * 64 for position in range(COUNT))
PLACEMENT = PlacementConfig(check_rule="axis-ramp-v1",
                            relation_vocabulary=("left-of", "right-of",
                                                 "above", "below"),
                            area_cap=0.9, margin=0.15)
GATES = IntakeGates(min_ink_pixels=100, min_strokes_whole_drawing=2,
                    max_text_length=200, max_atoms=64)

_FIT_DOCUMENT = {
    "config_version": 1,
    "generator": {"levels": [
        {"n_atoms": 3, "generalize_p": 0.0, "n_noise": 0, "relations": 2},
        {"n_atoms": 2, "generalize_p": 1.0, "n_noise": 1, "relations": 1},
        {"n_atoms": 0, "generalize_p": 0.0, "n_noise": 4, "relations": 0},
    ]},
    "generalize": {"provider": "fake", "model": None,
                   "instruction_template": None},
    "openrouter": {"default_model": "test/fake", "max_concurrency": 1,
                   "requests_per_second": 100.0, "timeout_seconds": 5.0,
                   "retry_limit": 0, "response_format_mode": "json_schema"},
    "fit": {"split_salt": "fit-salt", "fit_count": 3, "holdout_count": 2,
            "synthetic_count": 6, "synthetic_seed": 11, "line_points": 5,
            "simplex_step": 0.25, "signal_line": 0.65,
            "ablation_line": 0.01},
    "harness": {"v3_trials_for_each_level": 4, "v3_seed": 5,
                "v6_trial_count": 4, "v6_seed": 6,
                "v6_tier1_widths": [2, 4], "v6_tier2_widths": [1, 2]},
    "tag": "dev-test",
}

TABLE = {f"item {position} of {image}": f"general {position}"
         for position in range(4) for image in range(COUNT)}


def _fit_config():
    return parse_fit_config(
        {**_FIT_DOCUMENT,
         "generator": {"levels": [dict(row) for row
                                  in _FIT_DOCUMENT["generator"]["levels"]]}},
        "test-fit")


def _index():
    """Six images, four elements each, boxed apart on a diagonal."""
    vocabulary = tuple(f"item {position} of {image}"
                       for image in range(COUNT) for position in range(4))
    vectors = np.eye(len(vocabulary), DIMENSION, dtype=np.float32)
    vectors[len(vocabulary) - 1, 0] = 1.0   # keep each row non-zero
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    vectors = (vectors / norms).astype(np.float32)
    incidence = np.asarray(
        [[image * 4 + position for position in range(4)]
         for image in range(COUNT)], dtype=np.int32)
    table = np.zeros((COUNT, 4, 4), dtype=np.float32)
    mask = np.ones((COUNT, 4), dtype=np.bool_)
    for image in range(COUNT):
        for position in range(4):
            corner = 0.05 + 0.2 * position
            table[image, position] = (corner, corner, corner + 0.15,
                                      corner + 0.15)
    # One near-full-frame slot for the area-cap path.
    table[0, 3] = (0.01, 0.01, 0.99, 0.99)
    return make_pool_index(
        index_id="f" * 64, image_ids=IDS,
        outline_vectors=np.zeros((COUNT, 6, DIMENSION), dtype=np.float32),
        outline_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        group_ids=IDS,
        pool_image_count=COUNT, vocabulary=vocabulary,
        pool_frequency=(1,) * len(vocabulary),
        vocabulary_vectors=vectors, incidence=incidence,
        element_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        box_table=table, box_mask=mask)


def test_the_set_is_byte_stable_for_one_seed() -> None:
    index = _index()
    config = _fit_config()
    first = synthetic_set(index, config, TABLE, PLACEMENT, seed=3, count=8)
    second = synthetic_set(index, config, TABLE, PLACEMENT, seed=3, count=8)
    assert canonical_json([row.record for row in first]) \
        == canonical_json([row.record for row in second])
    third = synthetic_set(index, config, TABLE, PLACEMENT, seed=4, count=8)
    assert canonical_json([row.record for row in first]) \
        != canonical_json([row.record for row in third])


def test_each_record_clears_the_layer_zero_gates() -> None:
    index = _index()
    config = _fit_config()
    for row in synthetic_set(index, config, TABLE, PLACEMENT, seed=3,
                             count=12):
        submission = validate_submission(row.record, GATES, 512)
        assert submission.atoms


def test_the_level_shapes_hold(subtests=None) -> None:
    index = _index()
    config = _fit_config()
    rng = np.random.default_rng(0)
    strong = synthetic_submission(index, 1, config.generator.levels[0],
                                  TABLE, PLACEMENT, rng)
    assert len(strong["impressions"]) == 3
    assert len(strong["relations"]) == 2
    assert len(strong["groups"]) == 4
    # Each relation names two declared groups.
    ids = {group["id"] for group in strong["groups"]}
    for row in strong["relations"]:
        assert set(row["of"]) <= ids
    noise_only = synthetic_submission(index, 1,
                                      config.generator.levels[2],
                                      TABLE, PLACEMENT, rng)
    assert len(noise_only["impressions"]) == 4
    assert noise_only["canvas_strokes"] == []
    assert noise_only["relations"] == []
    # Noise atoms come from the element lists of other images.
    own = {index.vocabulary[entry] for entry in index.incidence[1]}
    assert all(text not in own for text in noise_only["impressions"])


def test_full_generalization_reads_the_table() -> None:
    index = _index()
    config = _fit_config()
    rng = np.random.default_rng(1)
    row = synthetic_submission(index, 2, config.generator.levels[1],
                               TABLE, PLACEMENT, rng)
    own = {index.vocabulary[entry] for entry in index.incidence[2]}
    sampled = row["impressions"][:2]
    assert all(text.startswith("general ") for text in sampled)
    assert all(text not in own for text in sampled)


def test_relation_truth_follows_the_box_geometry() -> None:
    assert relation_between((0.1, 0.4, 0.3, 0.6),
                            (0.7, 0.4, 0.9, 0.6)) == "left-of"
    assert relation_between((0.7, 0.4, 0.9, 0.6),
                            (0.1, 0.4, 0.3, 0.6)) == "right-of"
    # The canvas y axis points down: a smaller y is above.
    assert relation_between((0.4, 0.05, 0.6, 0.25),
                            (0.4, 0.7, 0.6, 0.9)) == "above"
    assert relation_between((0.4, 0.7, 0.6, 0.9),
                            (0.4, 0.05, 0.6, 0.25)) == "below"


def test_the_emitted_relation_agrees_with_the_group_boxes() -> None:
    index = _index()
    config = _fit_config()
    rng = np.random.default_rng(2)
    record = synthetic_submission(index, 3, config.generator.levels[0],
                                  TABLE, PLACEMENT, rng)
    boxes = {}
    for group in record["groups"]:
        points = next(stroke["points"] for stroke in record["canvas_strokes"]
                      if stroke["group_id"] == group["id"])
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        boxes[group["id"]] = (min(xs), min(ys), max(xs), max(ys))
    for row in record["relations"]:
        first, second = row["of"]
        assert relation_between(boxes[first], boxes[second]) \
            == row["relation"]


def test_the_generator_hash_moves_with_its_determinants() -> None:
    config = _fit_config()
    base = generator_config_hash(config, "a" * 64, "b" * 64)
    assert generator_config_hash(config, "c" * 64, "b" * 64) != base
    assert generator_config_hash(config, "a" * 64, "d" * 64) != base
    moved = {**_FIT_DOCUMENT,
             "generator": {"levels": [
                 {"n_atoms": 4, "generalize_p": 0.0, "n_noise": 0,
                  "relations": 2},
                 *[dict(row) for row
                   in _FIT_DOCUMENT["generator"]["levels"][1:]],
             ]}}
    other = parse_fit_config(moved, "test-fit")
    assert generator_config_hash(other, "a" * 64, "b" * 64) != base
