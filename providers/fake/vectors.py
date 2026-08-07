"""Seeded vector helpers for the fake providers.

Spec: docs/specs/pool-curation.md section 8 and
docs/specs/pool-preparation.md section 8. The fake encoders derive
reproducible vectors from SHA-256 digests, thus two runs give
byte-for-byte equal output.
"""

import numpy as np
from numpy.typing import NDArray

from core.canonical import sha256_hex


def _seed_from(data: bytes | str) -> int:
    """The output is an integer seed built from the first 8 SHA-256 digest bytes."""
    return int(sha256_hex(data)[:16], 16)


def _unit_gaussian(seed: int, dimension: int) -> NDArray[np.float64]:
    """One seeded Gaussian vector with unit norm, float64, length dimension."""
    rng = np.random.default_rng(seed)
    vector = rng.standard_normal(dimension)
    return vector / np.linalg.norm(vector)
