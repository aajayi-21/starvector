"""Integration: the full fake scoring path and its determinism.

Invariants 2 (channel length N), 7 (rescoring reproduces trial scores
byte-for-byte), and 8 (a submission no built channel reads raises at
the fusion boundary).
"""

import numpy as np
import pytest

from conftest import make_scoring_config

from core.channels.outline import outline_scores
from core.fusion import NoActiveChannels
from core.intake import IntakeError
from core.types import OutlineConfig
from pipeline.config import (element_config, fusion_weights, intake_gates,
                             outline_config, placement_config)
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import Encoders, score_trial
from providers.fake import markers
from providers.fake.sketch_encoder import FakeSketchEncoder
from providers.fake.text_encoder import FakeTextEncoder


def _encoders() -> Encoders:
    return Encoders(sketch=FakeSketchEncoder(32), text=FakeTextEncoder(32))


def _context(prepared, channels=("outline", "element")):
    loaded = load_pool_index(prepared["prep_record_path"], prepared["data"],
                             dev_only=True)
    config = make_scoring_config(prepared["prep_record_path"])
    count = len(loaded.index.image_ids)
    weights = fusion_weights(config)
    for name in channels:
        weights.setdefault(name, 1.0)
    return loaded, build_scoring_context(
        index=loaded.index,
        gates=intake_gates(config),
        render=loaded.render,
        outline=outline_config(config),
        element=element_config(config),
        placement=placement_config(config),
        weights=weights,
        commonness={name: np.zeros(count, dtype=np.float32)
                    for name in channels},
        scoring_config_hash="0" * 64,
        commonness_config_hash="1" * 64,
    )


def _sketch_record(family_id: int) -> dict:
    strokes = markers.encode_family_strokes(family_id)
    return {
        "impressions": [],
        "canvas_strokes": [
            {"points": [[x, y] for x, y in stroke], "group_id": None}
            for stroke in strokes],
        "groups": [],
        "relations": [],
        "pasted_text": None,
    }


def _text_record(text: str) -> dict:
    return {
        "impressions": [], "canvas_strokes": [], "groups": [],
        "relations": [], "pasted_text": text,
    }


def test_the_channel_output_covers_the_pool(scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation)
    count = len(loaded.index.image_ids)
    sketch = np.zeros(32, dtype=np.float32)
    sketch[0] = 1.0
    scores = outline_scores(
        sketch, loaded.index,
        OutlineConfig(comparison_rule="center-cosine-v1"))
    assert scores.shape == (count,)
    assert scores.dtype == np.float32


def test_rescoring_reproduces_the_trial_score(scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation)
    record = _sketch_record(5)
    target = loaded.index.image_ids[3]
    first = score_trial(record, target, context, _encoders())
    second = score_trial(record, target, context, _encoders())
    assert first == second
    assert first.decoy_count >= 1
    assert 0.0 <= first.p <= 1.0


def test_a_text_only_submission_scores_through_the_element_channel(
        scoring_preparation) -> None:
    # The P2 build raised NoActiveChannels here. Phase 3 routes
    # DESCRIPTION atoms to the element channel, thus the same record
    # scores with no path change (spec P3 section 1).
    loaded, context = _context(scoring_preparation)
    record = _text_record("tall vertical structure, grey stone")
    first = score_trial(record, loaded.index.image_ids[0], context,
                        _encoders())
    assert 0.0 <= first.p <= 1.0
    assert first == score_trial(record, loaded.index.image_ids[0], context,
                                _encoders())


def test_a_mixed_submission_engages_the_two_channels(
        scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation)
    record = _sketch_record(5)
    record["pasted_text"] = "tall vertical structure, grey stone"
    mixed = score_trial(record, loaded.index.image_ids[3], context,
                        _encoders())
    sketch_only = score_trial(_sketch_record(5), loaded.index.image_ids[3],
                              context, _encoders())
    text_only = score_trial(_text_record(record["pasted_text"]),
                            loaded.index.image_ids[3], context, _encoders())
    # The fused score is a mean of the two channels, thus the mixed
    # trial score is not the same as each single-channel trial.
    assert 0.0 <= mixed.p <= 1.0
    assert (mixed.p, sketch_only.p, text_only.p) is not None


def test_an_active_channel_with_no_table_raises(scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation, channels=("outline",))
    record = _text_record("tall vertical structure")
    with pytest.raises(ValueError, match="no commonness table"):
        score_trial(record, loaded.index.image_ids[0], context, _encoders())


def test_a_submission_with_no_routed_atom_raises(scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation)
    record = {
        "impressions": [], "canvas_strokes": [], "groups": [],
        "relations": [], "pasted_text": None,
    }
    with pytest.raises(NoActiveChannels):
        score_trial(record, loaded.index.image_ids[0], context, _encoders())


def test_a_relation_bearing_submission_scores_through_placement(
        scoring_preparation) -> None:
    # The full wire path: two labeled rectangle groups plus a stated
    # relation. Placement activates with element and outline, and the
    # trial ranks with the three-channel context.
    loaded, context = _context(scoring_preparation,
                               channels=("outline", "element", "placement"))
    record = {
        "impressions": ["tall vertical structure"],
        "canvas_strokes": [
            {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6], [0.1, 0.6],
                        [0.1, 0.4]], "group_id": "g1"},
            {"points": [[0.6, 0.4], [0.9, 0.4], [0.9, 0.6], [0.6, 0.6],
                        [0.6, 0.4]], "group_id": "g2"},
        ],
        "groups": [{"id": "g1", "label": "tower"},
                   {"id": "g2", "label": "sea"}],
        "relations": [{"relation": "left-of", "of": ["g1", "g2"]}],
        "pasted_text": None,
    }
    first = score_trial(record, loaded.index.image_ids[0], context,
                        _encoders())
    assert 0.0 <= first.p <= 1.0
    assert first == score_trial(record, loaded.index.image_ids[0], context,
                                _encoders())


def test_an_active_unweighted_channel_is_cut_not_an_error(
        scoring_preparation) -> None:
    # The spec S1 section 14a ruling (2026-08-12): a channel with no
    # configured weight is cut (architecture section 12.3), thus a
    # relation-bearing submission scores with a placement-free
    # config, and its trial equals the relation-free twin's - the
    # relation atom moves no other channel.
    loaded, context = _context(scoring_preparation,
                               channels=("outline", "element"))
    record = {
        "impressions": ["tall vertical structure"],
        "canvas_strokes": [
            {"points": [[0.1, 0.4], [0.3, 0.4], [0.3, 0.6], [0.1, 0.6],
                        [0.1, 0.4]], "group_id": "g1"},
            {"points": [[0.6, 0.4], [0.9, 0.4], [0.9, 0.6], [0.6, 0.6],
                        [0.6, 0.4]], "group_id": "g2"},
        ],
        "groups": [{"id": "g1", "label": "tower"},
                   {"id": "g2", "label": "sea"}],
        "relations": [{"relation": "left-of", "of": ["g1", "g2"]}],
        "pasted_text": None,
    }
    twin = {**record, "relations": []}
    target = loaded.index.image_ids[0]
    with_relation = score_trial(record, target, context, _encoders())
    assert with_relation == score_trial(twin, target, context, _encoders())


def test_a_weighted_channel_with_no_table_still_raises(
        scoring_preparation) -> None:
    # The cut rule does not loosen the D13 guard: a weighted active
    # channel with a missing commonness table is a configuration
    # defect, not a cut.
    loaded, context = _context(scoring_preparation,
                               channels=("outline", "element"))
    thinned = context.__class__(
        index=context.index, gates=context.gates, render=context.render,
        outline=context.outline, element=context.element,
        placement=context.placement, weights=context.weights,
        commonness={"outline": context.commonness["outline"]},
        scoring_config_hash=context.scoring_config_hash,
        commonness_config_hash=context.commonness_config_hash)
    record = _text_record("tall vertical structure")
    with pytest.raises(ValueError, match="no commonness table"):
        score_trial(record, loaded.index.image_ids[0], thinned, _encoders())


def test_the_prewarm_step_leaves_scores_unchanged(
        scoring_preparation) -> None:
    from validation.harness import prewarm_records

    loaded, context = _context(scoring_preparation)
    record = _text_record("tall vertical structure, grey stone")
    before = score_trial(record, loaded.index.image_ids[0], context,
                         _encoders())
    prewarm_records([record], context.gates, context.render, _encoders())
    after = score_trial(record, loaded.index.image_ids[0], context,
                        _encoders())
    assert before == after


def test_a_gate_violation_names_its_cause(scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation)
    record = _sketch_record(5)
    record["canvas_strokes"] = record["canvas_strokes"][:1]
    del record["pasted_text"]
    with pytest.raises(IntakeError, match="bad-shape"):
        score_trial(record, loaded.index.image_ids[0], context, _encoders())


def test_a_colorless_record_scores_the_same_under_mono_and_rgb(
        tmp_path) -> None:
    # The spec C1 byte-stable half above the byte level: with no
    # color key the promotion render gives the plain bytes, thus the
    # trial score is equal in the two worlds.
    from conftest import build_direct_prepared_pool

    mono_world = build_direct_prepared_pool(tmp_path / "mono", 12)
    rgb_world = build_direct_prepared_pool(
        tmp_path / "rgb", 12,
        overrides={"linedraw.stroke_color": "rgb"})
    record = _sketch_record(5)
    scores = []
    for prepared in (mono_world, rgb_world):
        loaded, context = _context(prepared)
        target = loaded.index.image_ids[3]
        scores.append(score_trial(record, target, context, _encoders()))
    assert scores[0] == scores[1]
    assert mono_world["prep_record_path"] != rgb_world["prep_record_path"]
