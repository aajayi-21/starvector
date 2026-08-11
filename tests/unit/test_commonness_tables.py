"""Unit tests for the commonness table of each channel (P3 D11, P4 D13).

One table for each built channel the background activates, at one
shared key. Each table is the mean across the submissions that
activate its channel, with the contributor counts recorded — a mixed
background activates different channels with different subsets.
"""

import numpy as np
import pytest

from core.canonical import JsonValue
from core.types import (ElementConfig, IntakeGates, OutlineConfig,
                        PlacementConfig, RenderParams)
from pipeline.commonness import build_commonness_tables
from pipeline.score import Encoders
from providers.fake.sketch_encoder import FakeSketchEncoder
from providers.fake.text_encoder import FakeTextEncoder
from tests.conftest import make_pool_index

DIMENSION = 8
COUNT = 4
IDS = tuple(chr(97 + position) * 64 for position in range(COUNT))
GATES = IntakeGates(min_ink_pixels=0, min_strokes_whole_drawing=1,
                    max_text_length=200, max_atoms=64)
# The fake sketch encoder decodes markers from the rendered pixels and
# needs the production canvas height to do it.
RENDER = RenderParams(canvas_px=512, line_width_px=3)
OUTLINE = OutlineConfig(comparison_rule="center-cosine-v1")
ELEMENT = ElementConfig(comparison_rule="element-center-cosine-v1",
                        matching_rule="sinkhorn-slack-v1", epsilon=0.1,
                        sinkhorn_iterations=20, tier2_count=500, alpha=1.0)
PLACEMENT = PlacementConfig(check_rule="axis-ramp-v1",
                            relation_vocabulary=("left-of", "right-of",
                                                 "above", "below"),
                            area_cap=0.9, margin=0.15)


def _index():
    rng = np.random.default_rng(4)
    vectors = rng.standard_normal((COUNT, 6, DIMENSION))
    vectors /= np.linalg.norm(vectors, axis=2, keepdims=True)
    bank = rng.standard_normal((COUNT, DIMENSION))
    bank /= np.linalg.norm(bank, axis=1, keepdims=True)
    boxes = np.zeros((COUNT, 1, 4), dtype=np.float32)
    boxes[:, 0] = (0.1, 0.1, 0.4, 0.4)
    return make_pool_index(
        index_id="f" * 64, image_ids=IDS,
        outline_vectors=vectors.astype(np.float32),
        outline_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        group_ids=IDS,
        pool_image_count=COUNT,
        vocabulary=tuple(f"element {position}" for position in range(COUNT)),
        pool_frequency=(1,) * COUNT,
        vocabulary_vectors=bank.astype(np.float32),
        incidence=np.arange(COUNT, dtype=np.int32).reshape(COUNT, 1),
        element_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        box_table=boxes,
        box_mask=np.ones((COUNT, 1), dtype=np.bool_))


def _encoders() -> Encoders:
    return Encoders(sketch=FakeSketchEncoder(DIMENSION),
                    text=FakeTextEncoder(DIMENSION))


def _record(text: str | None, strokes: bool,
            relation: bool = False) -> JsonValue:
    paths = [{"points": [[0.1, 0.1], [0.9, 0.9]], "group_id": None},
             {"points": [[0.1, 0.9], [0.9, 0.1]], "group_id": None}]
    record = {
        "impressions": [], "canvas_strokes": list(paths) if strokes else [],
        "groups": [], "relations": [], "pasted_text": text,
    }
    if relation:
        record["canvas_strokes"] = list(record["canvas_strokes"]) + [
            {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6], [0.1, 0.6],
                        [0.1, 0.4]], "group_id": "g1"},
            {"points": [[0.6, 0.4], [0.9, 0.4], [0.9, 0.6], [0.6, 0.6],
                        [0.6, 0.4]], "group_id": "g2"},
        ]
        record["groups"] = [{"id": "g1", "label": "tower"},
                            {"id": "g2", "label": "boat"}]
        record["relations"] = [{"relation": "left-of", "of": ["g1", "g2"]}]
    return record


def _background(mode: str, count: int = 4):
    rows = []
    for position in range(count):
        text = f"a tower {position}" if mode in ("text", "mixed") else None
        rows.append((f"pair/{position:04d}",
                     _record(text, mode in ("sketch", "mixed"))))
    return rows


def _build(rows):
    return build_commonness_tables(
        _index(), rows, gates=GATES, render=RENDER,
        outline=OUTLINE, element=ELEMENT, placement=PLACEMENT,
        encoders=_encoders())


def test_the_sketch_mode_builds_the_outline_table_alone() -> None:
    built = _build(_background("sketch"))
    assert sorted(built.tables) == ["outline"]
    assert built.tables["outline"].shape == (COUNT,)
    assert built.tables["outline"].dtype == np.float32
    assert built.contributors == {"outline": 4}


def test_the_text_mode_builds_the_element_table_alone() -> None:
    built = _build(_background("text"))
    assert sorted(built.tables) == ["element"]
    assert built.contributors == {"element": 4}


def test_the_mixed_mode_builds_the_two_tables() -> None:
    built = _build(_background("mixed"))
    assert sorted(built.tables) == ["element", "outline"]


def test_the_build_ranges_across_each_activated_channel() -> None:
    # The content is a pure function of the background and the index
    # (ruling 2026-08-10): no caller argument can narrow the build.
    # The weighted-subset selection lives in build_scoring_context.
    built = _build(_background("mixed"))
    assert sorted(built.tables) == ["element", "outline"]


def test_a_mixed_background_means_across_activating_subsets() -> None:
    # Two sketch-only rows and two text-bearing rows (D13): the
    # outline table means across all four, the element table across
    # the two that hold text — and the counts say so.
    rows = sorted(_background("sketch", 2) + [
        (f"pair/{position:04d}", _record(f"a tower {position}", True))
        for position in (2, 3)])
    built = _build(rows)
    assert built.contributors == {"outline": 4, "element": 2}
    from core.intake import validate_submission
    from pipeline.score import channel_scores, encode_submissions

    text_rows = [record for _, record in rows
                 if record["pasted_text"] is not None]
    submissions = [validate_submission(record, GATES, RENDER.canvas_px)
                   for record in text_rows]
    encoded = encode_submissions(submissions, RENDER, _encoders())
    by_hand = np.mean(
        [channel_scores("element", row, _index(), OUTLINE, ELEMENT,
                        PLACEMENT).astype(np.float64)
         for row in encoded], axis=0)
    assert built.tables["element"] == pytest.approx(by_hand, abs=1e-6)


def test_a_relation_bearing_background_builds_the_placement_table() -> None:
    rows = sorted(_background("sketch", 2) + [
        (f"pair/{position:04d}", _record(None, True, relation=True))
        for position in (2, 3)])
    built = _build(rows)
    assert sorted(built.tables) == ["element", "outline", "placement"]
    # The rectangle groups hold labels, thus the element channel
    # activates with them. The placement subset is the relation rows.
    assert built.contributors["placement"] == 2
    assert built.contributors["outline"] == 4
    assert built.tables["placement"].shape == (COUNT,)


def test_the_table_is_the_mean_of_the_raw_channel_scores() -> None:
    from core.intake import validate_submission
    from pipeline.score import channel_scores, encode_submissions

    rows = _background("text")
    index = _index()
    submissions = [validate_submission(record, GATES, RENDER.canvas_px)
                   for _, record in rows]
    encoded = encode_submissions(submissions, RENDER, _encoders())
    by_hand = np.mean(
        [channel_scores("element", row, index, OUTLINE, ELEMENT,
                        PLACEMENT).astype(np.float64) for row in encoded],
        axis=0)
    assert _build(rows).tables["element"] == pytest.approx(by_hand, abs=1e-6)


def test_an_unsorted_background_raises() -> None:
    rows = list(reversed(_background("sketch")))
    with pytest.raises(ValueError, match="ascending by pair_key"):
        _build(rows)


def test_an_empty_background_raises() -> None:
    with pytest.raises(ValueError, match="background set is empty"):
        _build([])


def _hash_config(**overrides):
    from tests.conftest import make_scoring_config

    return make_scoring_config("unused-record.json", **overrides)


def test_the_key_enforces_the_two_sided_generator_identity(tmp_path) -> None:
    from pipeline.commonness import commonness_config_hash

    fit_path = tmp_path / "fit.json"
    fit_path.write_text("{}", encoding="utf-8")
    with_synthetic = _hash_config(
        **{"commonness.background_count": 12,
           "commonness.synthetic": {"fit_config": str(fit_path),
                                    "count": 6, "seed": 17}})
    plain = _hash_config()
    with pytest.raises(ValueError, match="generator_hash"):
        commonness_config_hash(with_synthetic, RENDER, "a" * 64, "b" * 64,
                               "c" * 64, generator_hash=None)
    with pytest.raises(ValueError, match="generator_hash"):
        commonness_config_hash(plain, RENDER, "a" * 64, "b" * 64,
                               "c" * 64, generator_hash="d" * 64)


def test_the_source_b_identity_moves_the_key(tmp_path) -> None:
    from pipeline.commonness import commonness_config_hash

    fit_path = tmp_path / "fit.json"
    fit_path.write_text("{}", encoding="utf-8")
    with_synthetic = _hash_config(
        **{"commonness.background_count": 12,
           "commonness.synthetic": {"fit_config": str(fit_path),
                                    "count": 6, "seed": 17}})
    plain = _hash_config()
    base = commonness_config_hash(plain, RENDER, "a" * 64, "b" * 64,
                                  "c" * 64)
    first = commonness_config_hash(with_synthetic, RENDER, "a" * 64,
                                   "b" * 64, "c" * 64,
                                   generator_hash="d" * 64)
    second = commonness_config_hash(with_synthetic, RENDER, "a" * 64,
                                    "b" * 64, "c" * 64,
                                    generator_hash="e" * 64)
    assert base != first
    assert first != second
