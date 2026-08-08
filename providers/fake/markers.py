"""Marker geometry shared by the fake sketch pairs and the fake encoder.

The fake pair source writes a family identifier into stroke geometry,
and the fake sketch encoder reads it back from the rendered pixels —
the canonical render keeps no metadata, thus the geometry is the one
carrier. The encoding: one sync stroke at a fixed height, plus one
full-width stroke for each set bit of the identifier, all in a
reserved band below the content area. Axis-aligned full-width lines
survive Bresenham rasterization and square dilation, which is what
makes the decode stable.
"""

from io import BytesIO

import numpy as np
from PIL import Image

from core.types import StrokePath

# In the two fake config hashes: a geometry change moves them.
MARKER_RULE = "rows-v1"

# The sync stroke: always on. A render without it is not a fake-pair
# sketch, and the decoder returns None.
SYNC_Y = 0.76

# Seven bit slots: family identifiers 0..127.
BIT_YS: tuple[float, ...] = tuple(0.79 + 0.03 * k for k in range(7))

# Fake content strokes stay at or above this line, thus the marker
# band stays clean after dilation.
CONTENT_MAX_Y = 0.70

# A slot row counts as on when its ink fraction is at or above this.
_ROW_INK_FRACTION = 0.9

# The decoder needs the slot rows to be apart after quantization and
# dilation. Below this canvas height the geometry is not designed to
# hold, and to decode garbage is a silent fallback (R14).
_MIN_HEIGHT = 384


def family_name(family_id: int) -> str:
    """The family string shared with the photo's embed_family chunk."""
    if not 0 <= family_id <= 127:
        raise ValueError(f"family_id must be in [0, 127], got {family_id}")
    return f"sketchpair-{family_id:04d}"


def encode_family_strokes(family_id: int) -> tuple[StrokePath, ...]:
    """The marker strokes for one family identifier.

    One sync stroke plus one full-width stroke for each set bit.
    """
    family_name(family_id)  # range check
    strokes: list[StrokePath] = [((0.0, SYNC_Y), (1.0, SYNC_Y))]
    for bit, y in enumerate(BIT_YS):
        if family_id & (1 << bit):
            strokes.append(((0.0, y), (1.0, y)))
    return tuple(strokes)


def _slot_is_on(ink: np.ndarray, y: float) -> bool:
    height, width = ink.shape
    center = round(y * (height - 1))
    half_window = max(3, height // 100)
    low = max(0, center - half_window)
    high = min(height, center + half_window + 1)
    window = ink[low:high]                       # (rows, width)
    row_fractions = window.sum(axis=1) / width   # (rows,)
    return bool((row_fractions >= _ROW_INK_FRACTION).any())


def decode_family(png_bytes: bytes) -> int | None:
    """Read the family identifier from one rendered sketch PNG.

    Returns None when the sync stroke is not there — the render is
    then not a fake-pair sketch. Raises on a canvas too small for the
    slot geometry.
    """
    with Image.open(BytesIO(png_bytes)) as image:
        pixels = np.asarray(image.convert("L"))   # (H, W)
    height = pixels.shape[0]
    if height < _MIN_HEIGHT:
        raise ValueError(
            f"canvas height {height} is below the marker minimum "
            f"{_MIN_HEIGHT}")
    ink = pixels < 128                            # (H, W) boolean
    if not _slot_is_on(ink, SYNC_Y):
        return None
    family_id = 0
    for bit, y in enumerate(BIT_YS):
        if _slot_is_on(ink, y):
            family_id |= 1 << bit
    return family_id
