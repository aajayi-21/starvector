"""Deterministic fake image encoder for tests.

Fills the ImageEncoder slot of docs/specs/pool-curation.md section 8.
Vectors come from seeded Gaussian samples, keyed by the PNG text chunks
that the fake corpus wrote. Near-duplicate pairs and cluster families
get reproducible cosine structure without a model.
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from core.canonical import canonical_json, sha256_hex
from core.types import Vectors
from providers.fake.chunks import read_fake_chunks
from providers.fake.vectors import _seed_from, _unit_gaussian


class FakeImageEncoder:
    """Fake encoder with scripted near-duplicate and family structure.

    Images that share an embed_family chunk get vectors near one shared
    base vector. The embed_jitter chunk selects the offset scale: "dup"
    gives an almost equal vector, all other values give a family-level
    distance. An image without an embed_family chunk gets a vector
    seeded from its bytes.

    instruction mirrors the joint-embedding field of the live image
    slot (spec P2c section 5): it moves the config hash — thus the
    cache and lineage identity — and moves no vector, so a scripted
    family structure stays in force across the P2c conditions.
    """

    def __init__(
        self, dimension: int, dup_epsilon: float = 0.05,
        family_epsilon: float = 0.7, instruction: str | None = None,
    ) -> None:
        self._dimension = dimension
        self._dup_epsilon = dup_epsilon
        self._family_epsilon = family_epsilon
        self._instruction = instruction

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake encoder parameters.

        The instruction is omitted at None (P2c R5), thus a config
        without one hashes as it did before the field existed.
        """
        document = {
            "provider": "fake-encoder",
            "dimension": self._dimension,
            "dup_epsilon": self._dup_epsilon,
            "family_epsilon": self._family_epsilon,
        }
        if self._instruction is not None:
            document["instruction"] = self._instruction
        return sha256_hex(canonical_json(document))

    def encode_images(self, images: Sequence[bytes]) -> Vectors:
        """Encode a batch of images.

        The output is float32 with shape (B, dimension), one unit-norm
        row for each image.
        """
        if not images:
            return np.zeros((0, self._dimension), dtype=np.float32)
        stacked = np.stack([self._encode_one(image) for image in images])
        stacked /= np.linalg.norm(stacked, axis=1, keepdims=True)  # (B, dimension)
        return stacked.astype(np.float32)

    def _encode_one(self, image_bytes: bytes) -> NDArray[np.float64]:
        """One vector for one image, float64, before the batch cast."""
        chunks = read_fake_chunks(image_bytes)
        family = chunks.get("embed_family")
        if family is None:
            return _unit_gaussian(_seed_from(image_bytes), self._dimension)
        base = _unit_gaussian(_seed_from("family:" + family), self._dimension)
        offset = _unit_gaussian(_seed_from(image_bytes), self._dimension)
        if chunks.get("embed_jitter") == "dup":
            epsilon = self._dup_epsilon
        else:
            epsilon = self._family_epsilon
        blend = base + epsilon * offset
        return blend / np.linalg.norm(blend)
