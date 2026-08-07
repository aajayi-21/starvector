"""Stage p06 crop geometry. Pure functions on pixel rectangles.

Spec: docs/specs/pool-preparation.md section 10, stage p06, and
decision D6. The runner loads drawings and encodes the outputs - this
module only cuts.
"""

import math
from io import BytesIO

from PIL import Image

# The fixed row sequence of one outline stack (spec section 10, p06):
# row 0 is the full image, rows 1 through 5 are the D6 crops.
ROW_LAYOUT: tuple[str, ...] = (
    "full",
    "center",
    "top-left",
    "top-right",
    "bottom-left",
    "bottom-right",
)


def outline_crop_boxes(
    width: int, height: int, crop_fraction: float
) -> tuple[tuple[int, int, int, int], ...]:
    """The five D6 crop rectangles for one width by height canvas.

    Each crop side is the floor of the canvas side times
    crop_fraction, in pixels. The output sequence is center,
    top-left, top-right, bottom-left, bottom-right - ROW_LAYOUT rows
    1 through 5. Each rectangle is (left, top, right, bottom) pixel
    positions, in the PIL crop sequence. A crop side below one pixel
    raises (R14).
    """
    if width < 1 or height < 1:
        raise ValueError(f"canvas {width}x{height} is not positive")
    if not 0.0 < crop_fraction <= 1.0:
        raise ValueError(f"crop_fraction {crop_fraction} is not in (0, 1]")
    crop_width = math.floor(width * crop_fraction)
    crop_height = math.floor(height * crop_fraction)
    if crop_width < 1 or crop_height < 1:
        raise ValueError(
            f"crop {crop_width}x{crop_height} from canvas {width}x{height} "
            f"at fraction {crop_fraction} is below one pixel"
        )
    center_left = (width - crop_width) // 2
    center_upper = (height - crop_height) // 2
    return (
        (center_left, center_upper, center_left + crop_width, center_upper + crop_height),
        (0, 0, crop_width, crop_height),
        (width - crop_width, 0, width, crop_height),
        (0, height - crop_height, crop_width, height),
        (width - crop_width, height - crop_height, width, height),
    )


def outline_crop_images(drawing_png: bytes, crop_fraction: float) -> tuple[bytes, ...]:
    """One full drawing plus its five crops, as six PNG byte strings.

    Row 0 is the input PNG unchanged. Rows 1 through 5 are the D6
    crops, cut with PIL and encoded again as PNG. The row sequence is
    ROW_LAYOUT.
    """
    crops: list[bytes] = []
    with Image.open(BytesIO(drawing_png)) as image:
        image.load()
        width, height = image.size
        for box in outline_crop_boxes(width, height, crop_fraction):
            buffer = BytesIO()
            image.crop(box).save(buffer, format="PNG")
            crops.append(buffer.getvalue())
    return (drawing_png, *crops)
