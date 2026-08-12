"""Stage p06 crop geometry. Pure functions on pixel rectangles.

Spec: docs/specs/pool-preparation.md section 10, stage p06, and
decision D6, extended by docs/specs/photo-embedding-bridge.md
sections 4 and 6. The runner loads drawings or photographs and
encodes the outputs - this module only cuts and renders.
"""

import math
from io import BytesIO

from PIL import Image
from PIL.PngImagePlugin import PngInfo

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


def photo_source_token(canvas_px: int, grayscale: bool = False) -> str:
    """The cache-key token of the photograph path (spec P2c section 4).

    It sits in the position the drawer hash holds on the linedraw
    path, thus the two paths cannot share a cached vector. It covers
    the canonical render rule and its parameters — the grayscale
    variant of the ruling recorded in spec P2c section 9a keys its
    own tree.
    """
    token = f"photo-canonical-v1:{canvas_px}"
    return token + ":grayscale" if grayscale else token


def photo_canonical(photo_bytes: bytes, canvas_px: int,
                    grayscale: bool = False) -> bytes:
    """The canonical photograph render (spec P2c section 4, D2).

    One deterministic rule, shared by the pool and the V1 inserted
    photographs (P2c R2): decode, convert to RGB — or to eight-bit
    grayscale for the photo-gray condition (P2c section 9a) — scale
    so the long side equals canvas_px, encode as PNG. No EXIF
    transform. PNG text chunks stay in the output — the fake
    providers script their cosine structure in them, and a live
    photograph's metadata is inert to the encoder.
    """
    if canvas_px < 1:
        raise ValueError(f"canvas_px {canvas_px} is not positive")
    with Image.open(BytesIO(photo_bytes)) as image:
        image.load()
        chunks = {key: value for key, value
                  in dict(getattr(image, "text", {}) or {}).items()
                  if isinstance(value, str)}
        converted = image.convert("L" if grayscale else "RGB")
    width, height = converted.size
    scale = canvas_px / max(width, height)
    scaled = converted.resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.LANCZOS)
    info = PngInfo()
    for key in sorted(chunks):
        info.add_text(key, chunks[key])
    buffer = BytesIO()
    scaled.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()
