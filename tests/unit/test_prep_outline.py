"""Unit tests for the p06 crop geometry against pinned rectangles."""

from io import BytesIO

import pytest
from PIL import Image

from pool.preparation.stages.outline import (
    ROW_LAYOUT,
    outline_crop_boxes,
    outline_crop_images,
)


def _png_bytes(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("L", (width, height), 255).save(buffer, format="PNG")
    return buffer.getvalue()


def test_row_layout_is_pinned() -> None:
    assert ROW_LAYOUT == (
        "full", "center", "top-left", "top-right", "bottom-left", "bottom-right",
    )


def test_512_at_fraction_06_pins_the_rectangles() -> None:
    boxes = outline_crop_boxes(512, 512, 0.6)
    # floor(512 * 0.6) == 307
    assert boxes == (
        (102, 102, 409, 409),
        (0, 0, 307, 307),
        (205, 0, 512, 307),
        (0, 205, 307, 512),
        (205, 205, 512, 512),
    )


def test_fraction_one_gives_the_full_canvas_five_times() -> None:
    boxes = outline_crop_boxes(512, 512, 1.0)
    assert boxes == ((0, 0, 512, 512),) * 5


def test_non_square_canvas() -> None:
    boxes = outline_crop_boxes(100, 60, 0.5)
    assert boxes == (
        (25, 15, 75, 45),
        (0, 0, 50, 30),
        (50, 0, 100, 30),
        (0, 30, 50, 60),
        (50, 30, 100, 60),
    )


def test_fraction_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="crop_fraction"):
        outline_crop_boxes(512, 512, 0.0)
    with pytest.raises(ValueError, match="crop_fraction"):
        outline_crop_boxes(512, 512, 1.1)


def test_crop_below_one_pixel_raises() -> None:
    with pytest.raises(ValueError, match="below one pixel"):
        outline_crop_boxes(1, 1, 0.6)


def test_crop_images_row_sequence_and_dimensions() -> None:
    drawing = _png_bytes(512, 512)
    rows = outline_crop_images(drawing, 0.6)
    assert len(rows) == len(ROW_LAYOUT)
    # Row 0 is the input PNG unchanged.
    assert rows[0] == drawing
    sizes = []
    for row in rows:
        with Image.open(BytesIO(row)) as image:
            sizes.append(image.size)
    assert sizes == [(512, 512)] + [(307, 307)] * 5


def test_crop_images_non_square() -> None:
    drawing = _png_bytes(100, 60)
    rows = outline_crop_images(drawing, 0.5)
    sizes = []
    for row in rows[1:]:
        with Image.open(BytesIO(row)) as image:
            sizes.append(image.size)
    assert sizes == [(50, 30)] * 5


def test_crop_images_are_deterministic() -> None:
    drawing = _png_bytes(64, 64)
    assert outline_crop_images(drawing, 0.6) == outline_crop_images(drawing, 0.6)
