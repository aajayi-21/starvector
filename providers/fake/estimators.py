"""Deterministic fake estimators for text coverage and object fraction.

Fill the TextCoverageEstimator and SalientObjectEstimator slots of
docs/specs/pool-curation.md section 8. Each estimator reads a scripted
fraction from a PNG text chunk.
"""

from collections.abc import Sequence

import numpy as np

from core.canonical import canonical_json, sha256_hex
from core.types import FloatArray
from providers.fake.chunks import read_fake_chunks


def _read_fraction(image_bytes: bytes, chunk_key: str) -> float:
    """One scripted fraction from a named chunk.

    A missing chunk, a chunk that does not parse as a number, or a
    value out of [0, 1] raises ValueError.
    """
    chunks = read_fake_chunks(image_bytes)
    text = chunks.get(chunk_key)
    if text is None:
        raise ValueError(f"{chunk_key} chunk is missing")
    value = float(text)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{chunk_key} value {value} is out of [0, 1]")
    return value


class FakeTextCoverageEstimator:
    """Estimator that reads the fake_text_coverage chunk."""

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake text-coverage parameters."""
        return sha256_hex(canonical_json({"provider": "fake-text-coverage"}))

    def estimate_text_coverage(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), one scripted fraction for each image."""
        return np.asarray(
            [_read_fraction(image, "fake_text_coverage") for image in images],
            dtype=np.float32,
        )


class FakeSalientObjectEstimator:
    """Estimator that reads the fake_object_fraction chunk."""

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake salient-object parameters."""
        return sha256_hex(canonical_json({"provider": "fake-salient-object"}))

    def estimate_salient_object_fraction(self, images: Sequence[bytes]) -> FloatArray:
        """The output is float32 (B,), one scripted fraction for each image."""
        return np.asarray(
            [_read_fraction(image, "fake_object_fraction") for image in images],
            dtype=np.float32,
        )
