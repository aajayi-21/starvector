"""Deterministic fake sketch encoder for tests.

Fills the SketchEncoder slot of docs/specs/scoring-path.md section 8.
The canonical render carries no metadata, thus this encoder reads the
family marker from the rendered pixels (providers/fake/markers.py) and
returns the same family-seeded base vector FakeImageEncoder gives the
paired photograph — the offline positive signal for the V1 harness. A
render without a marker gets a vector seeded from its bytes, the
no-information condition.
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from core.canonical import canonical_json, sha256_hex
from core.types import Vectors
from providers.fake import markers
from providers.fake.vectors import _seed_from, _unit_gaussian


class FakeSketchEncoder:
    """Fake encoder keyed by the rendered marker geometry."""

    def __init__(self, dimension: int, family_epsilon: float = 0.05) -> None:
        self._dimension = dimension
        self._family_epsilon = family_epsilon

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake encoder parameters."""
        return sha256_hex(canonical_json({
            "provider": "fake-sketch-encoder",
            "dimension": self._dimension,
            "family_epsilon": self._family_epsilon,
            "marker_rule": markers.MARKER_RULE,
        }))

    def encode_images(self, images: Sequence[bytes]) -> Vectors:
        """Encode a batch of rendered sketch PNG images.

        The output is float32 with shape (B, dimension), one unit-norm
        row for each image.
        """
        if not images:
            return np.zeros((0, self._dimension), dtype=np.float32)
        stacked = np.stack([self._encode_one(image) for image in images])
        stacked /= np.linalg.norm(stacked, axis=1, keepdims=True)  # (B, d)
        return stacked.astype(np.float32)

    def _encode_one(self, image_bytes: bytes) -> NDArray[np.float64]:
        family_id = markers.decode_family(image_bytes)
        if family_id is None:
            return _unit_gaussian(_seed_from(image_bytes), self._dimension)
        base = _unit_gaussian(
            _seed_from("family:" + markers.family_name(family_id)),
            self._dimension)
        offset = _unit_gaussian(_seed_from(image_bytes), self._dimension)
        blend = base + self._family_epsilon * offset
        return blend / np.linalg.norm(blend)
