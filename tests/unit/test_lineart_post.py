"""Tests for the pure line-drawing post-processing in core/lineart.py."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from core.lineart import binarize_mask, prune_short_segments, render_canonical


def test_binarize_dark_lines():
    gray = np.array([[0.2, 0.8], [0.0, 1.0]], dtype=np.float32)
    mask = binarize_mask(gray, threshold=0.5, lines_are_dark=True)
    assert mask.dtype == np.bool_
    assert np.array_equal(mask, [[True, False], [True, False]])


def test_binarize_light_lines():
    gray = np.array([[0.2, 0.8], [0.0, 1.0]], dtype=np.float32)
    mask = binarize_mask(gray, threshold=0.5, lines_are_dark=False)
    assert np.array_equal(mask, [[False, True], [False, True]])


def test_binarize_pixel_equal_to_threshold_is_a_stroke():
    gray = np.array([[0.5]], dtype=np.float32)
    assert binarize_mask(gray, threshold=0.5, lines_are_dark=True)[0, 0]
    assert binarize_mask(gray, threshold=0.5, lines_are_dark=False)[0, 0]


def test_binarize_rejects_non_2d():
    with pytest.raises(ValueError):
        binarize_mask(np.zeros((2, 2, 3), dtype=np.float32), 0.5, True)


def test_prune_removes_small_component_and_keeps_large():
    mask = np.zeros((12, 12), dtype=bool)
    mask[1:4, 1:4] = True    # 9 pixels: pruned at min_pixels 10
    mask[7:9, 3:8] = True    # 10 pixels: kept at min_pixels 10
    pruned = prune_short_segments(mask, min_pixels=10)
    assert not pruned[1:4, 1:4].any()
    assert pruned[7:9, 3:8].all()
    assert int(pruned.sum()) == 10


def test_prune_diagonal_chain_is_one_component():
    mask = np.zeros((8, 8), dtype=bool)
    for index in range(5):
        mask[index, index] = True
    assert prune_short_segments(mask, min_pixels=5).sum() == 5
    assert prune_short_segments(mask, min_pixels=6).sum() == 0


def test_prune_min_pixels_zero_and_one_keep_everything():
    mask = np.zeros((4, 4), dtype=bool)
    mask[0, 0] = True
    mask[3, 3] = True
    assert np.array_equal(prune_short_segments(mask, min_pixels=0), mask)
    assert np.array_equal(prune_short_segments(mask, min_pixels=1), mask)


def test_prune_does_not_change_the_input():
    mask = np.zeros((4, 4), dtype=bool)
    mask[0, 0] = True
    prune_short_segments(mask, min_pixels=2)
    assert mask[0, 0]


def test_render_square_output_with_two_pixel_values():
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:5, 1:7] = True
    png = render_canonical(mask, canvas_size=32, line_width=1)
    with Image.open(BytesIO(png)) as decoded:
        assert decoded.size == (32, 32)
        assert decoded.mode == "L"
        values = set(np.asarray(decoded).ravel().tolist())
    assert values == {0, 255}


def test_render_dilation_reaches_line_width():
    mask = np.zeros((32, 32), dtype=bool)
    mask[16, 4:28] = True
    png = render_canonical(mask, canvas_size=32, line_width=3)
    with Image.open(BytesIO(png)) as decoded:
        pixels = np.asarray(decoded)
    column = pixels[:, 16]
    assert int((column == 0).sum()) >= 3


def test_render_byte_identical_across_two_calls():
    mask = np.zeros((16, 16), dtype=bool)
    mask[4:12, 8] = True
    assert render_canonical(mask, 64, 3) == render_canonical(mask, 64, 3)


def test_render_rejects_bad_parameters():
    mask = np.zeros((4, 4), dtype=bool)
    with pytest.raises(ValueError):
        render_canonical(mask, canvas_size=0, line_width=3)
    with pytest.raises(ValueError):
        render_canonical(mask, canvas_size=32, line_width=0)
