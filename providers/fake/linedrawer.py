"""Deterministic fake line drawer for tests.

Fills the LineDrawer slot of docs/specs/pool-preparation.md section 8.
The output is a seeded drawing derived from the SHA-256 digest of the
input bytes. Each tEXt chunk of a PNG source is copied into the output
PNG, plus a fake_line_of chunk with the digest, because stage p06
encodes the drawing bytes and the fake image encoder reads its
embed_family and embed_jitter chunks from them.
"""

from collections.abc import Sequence
from io import BytesIO

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from core.canonical import canonical_json, sha256_hex
from providers.fake.chunks import read_fake_chunks
from providers.fake.vectors import _seed_from

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class FakeLineDrawer:
    """Line drawer with one seeded black-on-white PNG for each image."""

    def __init__(self, canvas_size: int = 64) -> None:
        self._canvas_size = canvas_size

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake line-drawer parameters."""
        return sha256_hex(canonical_json({
            "provider": "fake-line-drawer",
            "canvas_size": self._canvas_size,
        }))

    def draw_lines(self, images: Sequence[bytes]) -> list[bytes]:
        """One canonical PNG for each image, index-aligned.

        The output rows are square mode "L" PNG bytes at the configured
        canvas dimensions, black strokes on white. Equal input bytes
        give equal output bytes.
        """
        return [self._draw_one(image_bytes) for image_bytes in images]

    def _draw_one(self, image_bytes: bytes) -> bytes:
        """One seeded drawing plus the copied and added tEXt chunks."""
        size = self._canvas_size
        rng = np.random.default_rng(_seed_from(image_bytes))
        pixels = np.full((size, size), 255, dtype=np.uint8)
        # Seeded strokes: three rectangle outlines and two full-width lines.
        for _ in range(3):
            x0 = int(rng.integers(0, size - 1))
            y0 = int(rng.integers(0, size - 1))
            x1 = int(rng.integers(x0 + 1, size))
            y1 = int(rng.integers(y0 + 1, size))
            pixels[y0, x0 : x1 + 1] = 0
            pixels[y1, x0 : x1 + 1] = 0
            pixels[y0 : y1 + 1, x0] = 0
            pixels[y0 : y1 + 1, x1] = 0
        for _ in range(2):
            pixels[int(rng.integers(0, size)), :] = 0
        # Only a PNG source has tEXt chunks to copy. Other formats get
        # the fake_line_of chunk only.
        chunks: dict[str, str] = {}
        if image_bytes.startswith(_PNG_MAGIC):
            chunks = read_fake_chunks(image_bytes)
        chunks["fake_line_of"] = sha256_hex(image_bytes)
        info = PngInfo()
        for chunk_key, chunk_value in sorted(chunks.items()):
            info.add_text(chunk_key, chunk_value)
        buffer = BytesIO()
        Image.fromarray(pixels, mode="L").save(buffer, format="PNG", pnginfo=info)
        return buffer.getvalue()
