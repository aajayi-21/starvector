"""Integration: the full fake scoring path and its determinism.

Invariants 2 (channel length N), 7 (rescoring reproduces trial scores
byte-for-byte), and 8 (text-only raises at the fusion boundary).
"""

import numpy as np
import pytest

from conftest import make_scoring_config

from core.channels.outline import outline_scores
from core.fusion import NoActiveChannels
from core.intake import IntakeError
from core.types import OutlineConfig
from pipeline.config import intake_gates, outline_config, fusion_weights
from pipeline.context import build_scoring_context, load_pool_index
from pipeline.score import score_trial
from providers.fake import markers
from providers.fake.sketch_encoder import FakeSketchEncoder


def _context(prepared):
    loaded = load_pool_index(prepared["prep_record_path"], prepared["data"],
                             dev_only=True)
    config = make_scoring_config(prepared["prep_record_path"])
    count = len(loaded.index.image_ids)
    return loaded, build_scoring_context(
        index=loaded.index,
        gates=intake_gates(config),
        render=loaded.render,
        outline=outline_config(config),
        weights=fusion_weights(config),
        commonness={"outline": np.zeros(count, dtype=np.float32)},
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
    encoder = FakeSketchEncoder(32)
    record = _sketch_record(5)
    target = loaded.index.image_ids[3]
    first = score_trial(record, target, context, encoder)
    second = score_trial(record, target, context, FakeSketchEncoder(32))
    assert first == second
    assert first.decoy_count >= 1
    assert 0.0 <= first.p <= 1.0


def test_a_text_only_submission_raises_no_active_channels(
        scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation)
    record = {
        "impressions": ["tall vertical structure"],
        "canvas_strokes": [], "groups": [], "relations": [],
        "pasted_text": None,
    }
    with pytest.raises(NoActiveChannels):
        score_trial(record, loaded.index.image_ids[0], context,
                    FakeSketchEncoder(32))


def test_a_gate_violation_names_its_cause(scoring_preparation) -> None:
    loaded, context = _context(scoring_preparation)
    record = _sketch_record(5)
    record["canvas_strokes"] = record["canvas_strokes"][:1]
    del record["pasted_text"]
    with pytest.raises(IntakeError, match="bad-shape"):
        score_trial(record, loaded.index.image_ids[0], context,
                    FakeSketchEncoder(32))
