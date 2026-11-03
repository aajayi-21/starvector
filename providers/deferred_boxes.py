"""The deferred element_boxes slot (spec PP1 build item B8).

Placement is cut on the current lineage, thus the boxes supply nothing
until a fit reopens it. This provider answers "not located" for each
element and makes no POST. The stage writes its usual artifacts, and a
scoring config that names placement against this hash is refused at the
boundary (validation/harness.py). Provider caches are additive, thus
the boxes can be bought after the fact in a new preparation.
"""

from collections.abc import Mapping, Sequence

from core.canonical import canonical_json, sha256_hex
from providers.protocols import Box

DEFERRED_BOXES_HASH = sha256_hex(canonical_json({"provider": "deferred-boxes"}))


class DeferredElementBoxDetector:
    """ElementBoxDetector with no model behind it."""

    @property
    def config_hash(self) -> str:
        return DEFERRED_BOXES_HASH

    def detect_boxes(
        self, images: Sequence[bytes], element_lists: Sequence[Sequence[str]]
    ) -> Sequence[Mapping[str, Box | None]]:
        """One None for each queried element of each image."""
        return [{element: None for element in elements}
                for elements in element_lists]
