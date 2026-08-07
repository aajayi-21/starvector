"""Deterministic fake zero-shot image classifier for tests.

Fills the ZeroShotImageClassifier slot of docs/specs/pool-curation.md
section 8. The fake_label PNG chunk scripts the winning label.
"""

from collections.abc import Sequence

import numpy as np

from core.canonical import canonical_json, sha256_hex
from core.types import FloatArray
from providers.fake.chunks import read_fake_chunks


class FakeZeroShotImageClassifier:
    """Classifier that reads the winning label from the fake_label chunk."""

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake classifier parameters."""
        return sha256_hex(canonical_json({"provider": "fake-classifier"}))

    def classify(self, images: Sequence[bytes], labels: Sequence[str]) -> FloatArray:
        """Classify each image against the closed label set.

        The winning label gets 0.9, and the other labels share the
        remaining 0.1 equally. The output is float32 with shape (B, L),
        and each row sums to 1. A missing fake_label chunk, or a chunk
        value that is not in labels, raises ValueError.
        """
        matrix = np.zeros((len(images), len(labels)), dtype=np.float32)
        label_positions = {label: position for position, label in enumerate(labels)}
        other_count = len(labels) - 1
        for row, image_bytes in enumerate(images):
            chunks = read_fake_chunks(image_bytes)
            label = chunks.get("fake_label")
            if label is None:
                raise ValueError("fake_label chunk is missing")
            if label not in label_positions:
                raise ValueError(f"fake_label {label!r} is not in the label set")
            if other_count > 0:
                matrix[row, :] = 0.1 / other_count
                matrix[row, label_positions[label]] = 0.9
            else:
                # One label only: the winner gets the full 1.0.
                matrix[row, label_positions[label]] = 1.0
        return matrix
