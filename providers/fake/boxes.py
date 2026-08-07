"""Deterministic fake element box detector for tests.

Fills the ElementBoxDetector slot of docs/specs/pool-preparation.md
section 8. The fake_boxes PNG chunk scripts one box or null for named
elements. An unscripted element gets a hash-derived box, thus chunk-free
images (for example JPEG) get full coverage.
"""

import json
from collections.abc import Sequence

import numpy as np

from core.canonical import canonical_json, sha256_hex
from providers.fake.chunks import read_fake_chunks
from providers.fake.vectors import _seed_from
from providers.protocols import Box


def _validated_box(entry: object, digest: str, element: str) -> Box:
    """One Box parsed from a scripted chunk entry.

    The entry must be an array of four numbers in [0, 1] with x_min
    smaller than x_max and y_min smaller than y_max. Scripted geometry
    that breaks these limits raises ValueError with the image digest
    and the element named.
    """
    context = f"image {digest} element {element!r}"
    if (
        not isinstance(entry, list)
        or len(entry) != 4
        or not all(isinstance(value, (int, float)) for value in entry)
    ):
        raise ValueError(f"scripted box for {context} is not an array of four numbers")
    x_min, y_min, x_max, y_max = (float(value) for value in entry)
    if not all(0.0 <= value <= 1.0 for value in (x_min, y_min, x_max, y_max)):
        raise ValueError(f"scripted box for {context} is out of [0, 1]")
    if not (x_min < x_max and y_min < y_max):
        raise ValueError(f"scripted box for {context} has an empty extent")
    return Box(x_min, y_min, x_max, y_max)


def _derived_box(digest: str, element: str) -> Box:
    """One deterministic box seeded from the image digest plus the element.

    x_min and y_min are in [0, 0.8]. The width and the height are in
    [0.05, 0.2], thus the box stays in [0, 1] on the two axes.
    """
    rng = np.random.default_rng(_seed_from(digest + element))
    x_min = float(rng.uniform(0.0, 0.8))
    y_min = float(rng.uniform(0.0, 0.8))
    width = float(rng.uniform(0.05, 0.2))
    height = float(rng.uniform(0.05, 0.2))
    return Box(x_min, y_min, x_min + width, y_min + height)


class FakeElementBoxDetector:
    """Box detector that reads scripted boxes from the fake_boxes chunk."""

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake box-detector parameters."""
        return sha256_hex(canonical_json({"provider": "fake-box-detector"}))

    def detect_boxes(
        self, images: Sequence[bytes], element_lists: Sequence[Sequence[str]]
    ) -> list[dict[str, Box | None]]:
        """One mapping from element to Box or None for each image.

        element_lists is index-aligned with images, and the results
        are index-aligned with them. A scripted fake_boxes entry wins: null
        gives None, an array gives a validated Box. An unscripted
        element gets a hash-derived box. A length difference between
        the two inputs, or a duplicate element in one query, raises
        ValueError.
        """
        if len(images) != len(element_lists):
            raise ValueError(
                f"images has {len(images)} entries but element_lists has "
                f"{len(element_lists)}"
            )
        return [
            self._detect_one(image_bytes, elements)
            for image_bytes, elements in zip(images, element_lists, strict=True)
        ]

    def _detect_one(
        self, image_bytes: bytes, elements: Sequence[str]
    ) -> dict[str, Box | None]:
        """The boxes for one image, keys in the query sequence."""
        digest = sha256_hex(image_bytes)
        query = tuple(elements)
        if len(set(query)) != len(query):
            raise ValueError(f"duplicate query elements for image {digest}: {query!r}")
        chunks = read_fake_chunks(image_bytes)
        scripted: dict[str, object] = {}
        text = chunks.get("fake_boxes")
        if text is not None:
            document = json.loads(text)
            if not isinstance(document, dict):
                raise ValueError(
                    f"fake_boxes chunk of image {digest} is not a JSON object"
                )
            scripted = document
        result: dict[str, Box | None] = {}
        for element in query:
            if element in scripted:
                entry = scripted[element]
                result[element] = (
                    None if entry is None else _validated_box(entry, digest, element)
                )
            else:
                result[element] = _derived_box(digest, element)
        return result
