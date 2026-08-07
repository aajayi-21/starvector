"""Deterministic fake text encoder for tests.

Fills the TextEncoder slot of docs/specs/pool-preparation.md section 8.
Vectors are seeded Gaussian samples keyed by the input text. The
"text:" seed prefix keeps text seeds different from the byte-seeded
image vectors of the fake image encoder.
"""

from collections.abc import Sequence

import numpy as np

from core.canonical import canonical_json, sha256_hex
from core.types import Vectors
from providers.fake.vectors import _seed_from, _unit_gaussian


class FakeTextEncoder:
    """Text encoder with one seeded unit-norm vector for each input text."""

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake text-encoder parameters."""
        return sha256_hex(canonical_json({
            "provider": "fake-text-encoder",
            "dimension": self._dimension,
        }))

    def encode_texts(self, texts: Sequence[str]) -> Vectors:
        """Encode a batch of texts.

        The output is float32 with shape (B, dimension), one unit-norm
        row for each text. Equal texts give equal rows.
        """
        if not texts:
            return np.zeros((0, self._dimension), dtype=np.float32)
        stacked = np.stack([
            _unit_gaussian(_seed_from("text:" + text), self._dimension)
            for text in texts
        ])
        stacked /= np.linalg.norm(stacked, axis=1, keepdims=True)  # (B, dimension)
        return stacked.astype(np.float32)
