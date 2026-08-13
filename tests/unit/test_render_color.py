"""Unit tests for the spec C1 promotion rule and the RGB render."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from core.intake import (render_strokes, render_strokes_rgb,
                         render_submission_strokes, strokes_line_mask,
                         validate_submission)
from core.types import IntakeGates, RenderParams

CANVAS = 64
LOOSE = IntakeGates(min_ink_pixels=0, min_strokes_whole_drawing=1,
                    max_text_length=200, max_atoms=64)

STROKES = (((0.1, 0.3), (0.9, 0.3)), ((0.1, 0.7), (0.9, 0.7)))
CROSSING = (((0.1, 0.5), (0.9, 0.5)), ((0.5, 0.1), (0.5, 0.9)))


def _pixels(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(BytesIO(png)))


def test_mono_param_strips_colors_to_the_plain_bytes() -> None:
    mono = RenderParams(CANVAS, 3, "mono")
    colored = ("#c5221f", None)
    assert render_submission_strokes(STROKES, colored, mono) \
        == render_strokes(STROKES, CANVAS, 3)


def test_rgb_param_with_no_color_gives_the_plain_bytes() -> None:
    rgb = RenderParams(CANVAS, 3, "rgb")
    plain = render_strokes(STROKES, CANVAS, 3)
    assert render_submission_strokes(STROKES, None, rgb) == plain
    assert render_submission_strokes(STROKES, (None, None), rgb) == plain
    assert render_strokes_rgb(STROKES, (None, None), CANVAS, 3) == plain


def test_a_colored_stroke_promotes_to_an_exact_rgb_render() -> None:
    rgb = RenderParams(CANVAS, 3, "rgb")
    png = render_submission_strokes(STROKES, ("#c5221f", None), rgb)
    pixels = _pixels(png)
    assert pixels.shape == (CANVAS, CANVAS, 3)
    values = {tuple(v) for v in pixels.reshape(-1, 3)}
    # White paper, black ink, the one given color - no anti-aliasing.
    assert values == {(255, 255, 255), (0, 0, 0), (197, 34, 31)}
    assert png == render_submission_strokes(STROKES, ("#c5221f", None), rgb)


def test_the_stroke_that_comes_after_paints_above() -> None:
    rgb = RenderParams(CANVAS, 3, "rgb")
    png = render_submission_strokes(CROSSING, ("#c5221f", "#1a73e8"), rgb)
    pixels = _pixels(png)
    center = _pixels(render_strokes([CROSSING[1]], CANVAS, 3)) == 0
    # Where the second stroke paints, its blue wins - the crossing
    # included.
    assert (pixels[center] == (26, 115, 232)).all()


def test_an_unknown_rule_raises() -> None:
    with pytest.raises(ValueError, match="stroke_color"):
        render_submission_strokes(STROKES, ("#c5221f", None),
                                  RenderParams(CANVAS, 3, "sepia"))


def test_two_field_render_params_stay_equal_to_mono() -> None:
    assert RenderParams(512, 3) == RenderParams(512, 3, "mono")


def test_the_ink_gate_ignores_colors() -> None:
    record = {
        "impressions": [], "groups": [], "relations": [],
        "pasted_text": None,
        "canvas_strokes": [
            {"points": [[0.1, 0.3], [0.9, 0.3]], "group_id": None,
             "color": "#f0b429"},
        ],
    }
    plain = dict(record)
    plain["canvas_strokes"] = [
        {"points": [[0.1, 0.3], [0.9, 0.3]], "group_id": None}]
    gates = IntakeGates(min_ink_pixels=int(
        strokes_line_mask([((0.1, 0.3), (0.9, 0.3))], CANVAS).sum()),
        min_strokes_whole_drawing=1, max_text_length=200, max_atoms=64)
    assert len(validate_submission(record, gates, CANVAS).atoms) \
        == len(validate_submission(plain, gates, CANVAS).atoms)
