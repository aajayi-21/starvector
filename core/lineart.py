"""Pure line-drawing post-processing: binarize, prune, canonical render.

The R7 post-processing steps of docs/specs/pool-preparation.md section 4,
after model inference: threshold the model output to a boolean line
image, remove short segments, and render the canonical PNG. A LineDrawer
provider (spec section 8) applies these functions to its model output.
The functions are pure: no file access, no network, no clock, no RNG.
"""

from collections import deque
from io import BytesIO

import numpy as np
from numpy.typing import NDArray
from PIL import Image

# 8-connectivity: the eight row and column offsets around one pixel.
_NEIGHBOR_OFFSETS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1), (0, 1),
    (1, -1), (1, 0), (1, 1),
)


def binarize_mask(
    gray: NDArray[np.float32], threshold: float, lines_are_dark: bool
) -> NDArray[np.bool_]:
    """Threshold one grayscale image to a boolean line image.

    gray is a 2-D float array with values in [0, 1]. The output has the
    same shape, and an output pixel with value 1 is a line pixel. When
    the lines are dark (lines_are_dark), a pixel at or below the
    threshold becomes a line pixel. When the lines are light, a pixel
    at or above the threshold becomes a line pixel. A pixel equal to
    the threshold thus becomes a line pixel in the two polarities.
    """
    if gray.ndim != 2:
        raise ValueError(f"gray must be 2-D, got shape {gray.shape}")
    if lines_are_dark:
        return np.asarray(gray <= threshold)
    return np.asarray(gray >= threshold)


def prune_short_segments(
    mask: NDArray[np.bool_], min_pixels: int
) -> NDArray[np.bool_]:
    """Remove the 8-connected components with fewer than min_pixels pixels.

    The output is a new array with the same shape. A component keeps
    its pixels when its pixel count is at or above min_pixels, thus a
    min_pixels of 0 or 1 keeps the full image. Diagonal contact joins
    two pixels into one component (8-connectivity).
    """
    if mask.ndim != 2:
        raise ValueError(f"mask must be 2-D, got shape {mask.shape}")
    result = mask.copy()
    if min_pixels <= 1:
        return result
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    for start_row, start_col in zip(*np.nonzero(mask)):
        if visited[start_row, start_col]:
            continue
        # Walk across one 8-connected component, first-in first-out.
        component = [(int(start_row), int(start_col))]
        visited[start_row, start_col] = True
        queue = deque(component)
        while queue:
            row, col = queue.popleft()
            for row_offset, col_offset in _NEIGHBOR_OFFSETS:
                r, c = row + row_offset, col + col_offset
                if 0 <= r < height and 0 <= c < width and mask[r, c] and not visited[r, c]:
                    visited[r, c] = True
                    component.append((r, c))
                    queue.append((r, c))
        if len(component) < min_pixels:
            for row, col in component:
                result[row, col] = False
    return result


def _dilate_square(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """One binary dilation step with a 3 x 3 square structuring element."""
    height, width = mask.shape
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    result = np.zeros_like(mask)
    for row_start in (0, 1, 2):
        for col_start in (0, 1, 2):
            result |= padded[row_start : row_start + height, col_start : col_start + width]
    return result


def render_canonical(
    mask: NDArray[np.bool_], canvas_size: int, line_width: int
) -> bytes:
    """Render one boolean line image as canonical PNG bytes.

    The input is scaled to canvas_size x canvas_size with the
    nearest-neighbor rule, then dilated with a 3 x 3 square structuring
    element for (line_width - 1) // 2 iterations, thus an odd
    line_width gives each line a minimum width of line_width pixels.
    The output is a mode "L" PNG, white background, black strokes, with
    0 and 255 as the only pixel values — no anti-aliasing. Equal inputs
    give byte-for-byte equal output.
    """
    if mask.ndim != 2:
        raise ValueError(f"mask must be 2-D, got shape {mask.shape}")
    if canvas_size < 1:
        raise ValueError(f"canvas_size must be positive, got {canvas_size}")
    if line_width < 1:
        raise ValueError(f"line_width must be positive, got {line_width}")
    scaled_image = Image.fromarray(
        mask.astype(np.uint8) * 255, mode="L"
    ).resize((canvas_size, canvas_size), Image.Resampling.NEAREST)
    scaled = np.asarray(scaled_image, dtype=np.uint8) > 0  # (canvas_size, canvas_size)
    for _ in range((line_width - 1) // 2):
        scaled = _dilate_square(scaled)
    pixels = np.where(scaled, 0, 255).astype(np.uint8)
    buffer = BytesIO()
    Image.fromarray(pixels, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()
