"""The line-drawing model behind the LineDrawer slot - local only (U2).

Spec: docs/specs/pool-preparation.md section 8 and decisions D4 and D5.
The detector is the controlnet_aux lineart interface on the Informative
Drawings weights. Model inference, binarize, short-segment removal, and
the canonical re-render are all internal to this provider (R7), and the
config_hash covers the weights and all post-processing parameters. The
torch stack imports in the constructor, thus this module imports
without torch available. The device comes from the constructor, not
from the config, and is not part of the config_hash: the determinism
guarantee has the scope of one machine and environment (spec
section 14).
"""

import io
from collections.abc import Sequence
from typing import NamedTuple

import numpy as np
from PIL import Image

from core.canonical import canonical_json, sha256_hex


class LineartConfig(NamedTuple):
    """The full parameter set of the local line-drawing slot.

    The config_hash covers all fields, model weights and
    post-processing together - R7 makes the post-processing part of
    what the artifact is. The anti_alias field is in the hash, but the
    canonical render path has no anti-aliased branch - construction
    raises when the field asks for anti-aliasing.
    """

    weights_id: str
    coarse: bool
    detect_resolution: int
    binarize_threshold: float
    min_segment_px: int
    canvas_size: int
    line_width: int
    anti_alias: bool


def lineart_config_hash(config: LineartConfig) -> str:
    """The SHA-256 hex digest of the canonical JSON of the config."""
    return sha256_hex(canonical_json({"provider": "local-lineart", **config._asdict()}))


class LocalLineDrawer:
    """LineDrawer through the controlnet_aux lineart detector - the p05 slot.

    The detector loads at construction from the configured weights_id
    and moves to the device. draw_lines does the full R7 sequence for
    each image: detect, binarize, remove short segments, and re-render
    on the canonical canvas.
    """

    def __init__(self, config: LineartConfig, device: str = "cuda") -> None:
        if config.anti_alias:
            raise ValueError(
                "anti_alias must be False: the canonical render path has no "
                "anti-aliased branch"
            )
        from controlnet_aux import LineartDetector

        self._config = config
        self._detector = LineartDetector.from_pretrained(config.weights_id).to(device)

    @property
    def config_hash(self) -> str:
        return lineart_config_hash(self._config)

    def draw_lines(self, images: Sequence[bytes]) -> list[bytes]:
        """The output rows are canonical rendered line-drawing PNG bytes.

        Image bytes decode through PIL to RGB. The detector output
        becomes a grayscale float array in [0, 1]. Polarity, measured
        live 2026-08-07 with controlnet_aux 0.0.10: the lineart
        preprocessor gives bright lines on a dark background (mean
        grayscale 0.08 on a pool photograph), thus lines_are_dark is
        off here. The canonical render flips to dark strokes on white
        (D5).
        """
        from core.lineart import binarize_mask, prune_short_segments, render_canonical

        drawings: list[bytes] = []
        for image_bytes in images:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            detected = self._detector(
                image,
                coarse=self._config.coarse,
                detect_resolution=self._config.detect_resolution,
            )
            gray = np.asarray(detected.convert("L"), dtype=np.float32) / 255.0  # (H, W)
            mask = binarize_mask(gray, self._config.binarize_threshold, lines_are_dark=False)
            mask = prune_short_segments(mask, self._config.min_segment_px)
            drawings.append(
                render_canonical(mask, self._config.canvas_size, self._config.line_width)
            )
        return drawings
