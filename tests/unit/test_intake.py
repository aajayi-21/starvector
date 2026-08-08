"""Unit tests for the Layer 0 gates and the canonical stroke render."""

import numpy as np
import pytest
from PIL import Image
from io import BytesIO

from core.intake import (IntakeError, render_strokes, strokes_line_mask,
                         validate_submission)
from core.types import IntakeGates

GATES = IntakeGates(min_ink_pixels=100, min_strokes_whole_drawing=2,
                    max_text_length=200, max_atoms=64)
LOOSE = IntakeGates(min_ink_pixels=0, min_strokes_whole_drawing=1,
                    max_text_length=200, max_atoms=64)
CANVAS = 512


def _record(**overrides) -> dict:
    document = {
        "impressions": [],
        "canvas_strokes": [],
        "groups": [],
        "relations": [],
        "pasted_text": None,
    }
    document.update(overrides)
    return document


def _long_stroke(y: float = 0.5) -> dict:
    return {"points": [[0.0, y], [1.0, y]], "group_id": None}


def _dot_strokes(count: int) -> list[dict]:
    # Distinct pixels: one dot per column position.
    return [{"points": [[(i + 0.5) / CANVAS, 0.5]], "group_id": None}
            for i in range(count)]


def test_ink_gate_boundary_99_raises_100_passes() -> None:
    gates = IntakeGates(min_ink_pixels=100, min_strokes_whole_drawing=1,
                        max_text_length=200, max_atoms=200)
    with pytest.raises(IntakeError, match="min-ink") as caught:
        validate_submission(_record(canvas_strokes=_dot_strokes(99)),
                            gates, CANVAS)
    assert caught.value.cause == "min-ink"
    submission = validate_submission(_record(canvas_strokes=_dot_strokes(100)),
                                     gates, CANVAS)
    assert submission.atoms[-1].type == "WHOLE-DRAWING"


def test_stroke_count_boundary_1_raises_2_passes() -> None:
    with pytest.raises(IntakeError, match="min-strokes"):
        validate_submission(_record(canvas_strokes=[_long_stroke()]),
                            GATES, CANVAS)
    submission = validate_submission(
        _record(canvas_strokes=[_long_stroke(0.4), _long_stroke(0.6)]),
        GATES, CANVAS)
    assert len(submission.atoms) == 1


def test_text_length_boundary_200_passes_201_raises() -> None:
    validate_submission(_record(impressions=["x" * 200]), GATES, CANVAS)
    with pytest.raises(IntakeError, match="text-length"):
        validate_submission(_record(impressions=["x" * 201]), GATES, CANVAS)


def test_atom_count_boundary_64_passes_65_raises() -> None:
    validate_submission(_record(impressions=["row"] * 64), GATES, CANVAS)
    with pytest.raises(IntakeError, match="atom-count"):
        validate_submission(_record(impressions=["row"] * 65), GATES, CANVAS)


def test_point_off_the_unit_square_is_bad_shape() -> None:
    record = _record(canvas_strokes=[
        {"points": [[1.2, 0.5], [0.5, 0.5]], "group_id": None}])
    with pytest.raises(IntakeError, match="bad-shape"):
        validate_submission(record, LOOSE, CANVAS)


def test_non_finite_point_is_bad_shape() -> None:
    record = _record(canvas_strokes=[
        {"points": [[float("nan"), 0.5], [0.5, 0.5]], "group_id": None}])
    with pytest.raises(IntakeError, match="bad-shape"):
        validate_submission(record, LOOSE, CANVAS)


def test_unknown_relation_group_is_bad_shape() -> None:
    record = _record(relations=[{"relation": "left-of", "of": ["g1", "g2"]}])
    with pytest.raises(IntakeError, match="unknown group"):
        validate_submission(record, LOOSE, CANVAS)


def test_unknown_stroke_group_is_bad_shape() -> None:
    record = _record(canvas_strokes=[
        {"points": [[0.1, 0.1], [0.9, 0.9]], "group_id": "ghost"}])
    with pytest.raises(IntakeError, match="unknown group"):
        validate_submission(record, LOOSE, CANVAS)


def test_duplicate_group_id_is_bad_shape() -> None:
    record = _record(groups=[{"id": "g1", "label": ""},
                             {"id": "g1", "label": "again"}])
    with pytest.raises(IntakeError, match="duplicate"):
        validate_submission(record, LOOSE, CANVAS)


def test_unknown_top_level_key_is_bad_shape() -> None:
    record = _record()
    record["extra"] = 1
    with pytest.raises(IntakeError, match="bad-shape"):
        validate_submission(record, LOOSE, CANVAS)


def test_empty_impression_is_bad_shape() -> None:
    with pytest.raises(IntakeError, match="bad-shape"):
        validate_submission(_record(impressions=[""]), LOOSE, CANVAS)


def test_optional_point_entries_pass_and_extra_entries_do_not() -> None:
    good = _record(canvas_strokes=[
        {"points": [[0.1, 0.1, 12.5, 0.8], [0.9, 0.9, 13.0, 0.7]],
         "group_id": None}])
    validate_submission(good, LOOSE, CANVAS)
    bad = _record(canvas_strokes=[
        {"points": [[0.1, 0.1, 1.0, 1.0, 1.0], [0.9, 0.9]],
         "group_id": None}])
    with pytest.raises(IntakeError, match="bad-shape"):
        validate_submission(bad, LOOSE, CANVAS)


def test_render_is_deterministic_and_binary() -> None:
    strokes = (((0.1, 0.2), (0.8, 0.9)), ((0.5, 0.5),))
    first = render_strokes(strokes, CANVAS, 3)
    second = render_strokes(strokes, CANVAS, 3)
    assert first == second
    with Image.open(BytesIO(first)) as image:
        pixels = np.asarray(image.convert("L"))
    assert set(np.unique(pixels)) <= {0, 255}
    assert pixels.shape == (CANVAS, CANVAS)


def test_the_edge_point_one_maps_onto_the_last_pixel() -> None:
    mask = strokes_line_mask([((1.0, 1.0), (1.0, 1.0))], CANVAS)
    assert bool(mask[CANVAS - 1, CANVAS - 1])
    assert int(mask.sum()) == 1


def test_single_point_stroke_is_one_pixel_before_dilation() -> None:
    mask = strokes_line_mask([((0.5, 0.5),)], CANVAS)
    assert int(mask.sum()) == 1
