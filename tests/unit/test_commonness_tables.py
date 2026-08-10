"""Unit tests for the commonness table of each channel (P3 D11).

One table for each built channel the background activates, at one
shared key. A channel the background does not activate gets no table,
and a channel only part of the background activates raises.
"""

import numpy as np
import pytest

from core.canonical import JsonValue
from core.types import ElementConfig, IntakeGates, OutlineConfig, RenderParams
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


def _index():
    rng = np.random.default_rng(4)
    vectors = rng.standard_normal((COUNT, 6, DIMENSION))
    vectors /= np.linalg.norm(vectors, axis=2, keepdims=True)
    bank = rng.standard_normal((COUNT, DIMENSION))
    bank /= np.linalg.norm(bank, axis=1, keepdims=True)
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
        element_space_mean=np.zeros(DIMENSION, dtype=np.float32))


def _encoders() -> Encoders:
    return Encoders(sketch=FakeSketchEncoder(DIMENSION),
                    text=FakeTextEncoder(DIMENSION))


def _record(text: str | None, strokes: bool) -> JsonValue:
    paths = [{"points": [[0.1, 0.1], [0.9, 0.9]], "group_id": None},
             {"points": [[0.1, 0.9], [0.9, 0.1]], "group_id": None}]
    return {
        "impressions": [], "canvas_strokes": paths if strokes else [],
        "groups": [], "relations": [], "pasted_text": text,
    }


def _background(mode: str, count: int = 4):
    rows = []
    for position in range(count):
        text = f"a tower {position}" if mode in ("text", "mixed") else None
        rows.append((f"pair/{position:04d}",
                     _record(text, mode in ("sketch", "mixed"))))
    return rows


def _build(mode: str, channels=("outline", "element"), count: int = 4):
    return build_commonness_tables(
        _index(), _background(mode, count), gates=GATES, render=RENDER,
        outline=OUTLINE, element=ELEMENT, channels=channels,
        encoders=_encoders())


def test_the_sketch_mode_builds_the_outline_table_alone() -> None:
    tables = _build("sketch")
    assert sorted(tables) == ["outline"]
    assert tables["outline"].shape == (COUNT,)
    assert tables["outline"].dtype == np.float32


def test_the_text_mode_builds_the_element_table_alone() -> None:
    tables = _build("text")
    assert sorted(tables) == ["element"]


def test_the_mixed_mode_builds_the_two_tables() -> None:
    tables = _build("mixed")
    assert sorted(tables) == ["element", "outline"]


def test_a_channel_with_no_weight_gets_no_table() -> None:
    tables = _build("mixed", channels=("outline",))
    assert sorted(tables) == ["outline"]


def test_a_partly_activated_channel_raises() -> None:
    # Half the background carries a description and half does not: a
    # mean across part of the set is not a commonness table.
    rows = _background("sketch", 2) + [
        (f"pair/{position:04d}", _record(f"a tower {position}", True))
        for position in (2, 3)]
    with pytest.raises(ValueError, match="a table built from part"):
        build_commonness_tables(
            _index(), sorted(rows), gates=GATES, render=RENDER,
            outline=OUTLINE, element=ELEMENT,
            channels=("outline", "element"), encoders=_encoders())


def test_the_table_is_the_mean_of_the_raw_channel_scores() -> None:
    from pipeline.score import channel_scores, encode_submissions
    from core.intake import validate_submission

    rows = _background("text")
    index = _index()
    submissions = [validate_submission(record, GATES, RENDER.canvas_px)
                   for _, record in rows]
    encoded = encode_submissions(submissions, RENDER, _encoders())
    by_hand = np.mean(
        [channel_scores("element", row, index, OUTLINE, ELEMENT).astype(
            np.float64) for row in encoded], axis=0)
    assert _build("text")["element"] == pytest.approx(by_hand, abs=1e-6)


def test_an_unsorted_background_raises() -> None:
    rows = list(reversed(_background("sketch")))
    with pytest.raises(ValueError, match="ascending by pair_key"):
        build_commonness_tables(
            _index(), rows, gates=GATES, render=RENDER, outline=OUTLINE,
            element=ELEMENT, channels=("outline",), encoders=_encoders())


def test_an_empty_background_raises() -> None:
    with pytest.raises(ValueError, match="background set is empty"):
        build_commonness_tables(
            _index(), [], gates=GATES, render=RENDER, outline=OUTLINE,
            element=ELEMENT, channels=("outline",), encoders=_encoders())
