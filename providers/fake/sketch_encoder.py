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
    """Fake encoder keyed by the rendered marker geometry.

    instruction mirrors the joint-embedding field of the live sketch
    slot (spec P2c section 9a): it moves the config hash — thus the
    cache and lineage identity — and moves no vector, so the scripted
    family structure stays in force across the P2c conditions.
    """

    def __init__(self, dimension: int, family_epsilon: float = 0.05,
                 instruction: str | None = None) -> None:
        self._dimension = dimension
        self._family_epsilon = family_epsilon
        self._instruction = instruction

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake encoder parameters.

        The instruction is omitted at None (P2c R5), thus a config
        without one hashes as it did before the field existed.
        """
        document = {
            "provider": "fake-sketch-encoder",
            "dimension": self._dimension,
            "family_epsilon": self._family_epsilon,
            "marker_rule": markers.MARKER_RULE,
        }
        if self._instruction is not None:
            document["instruction"] = self._instruction
        return sha256_hex(canonical_json(document))

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
