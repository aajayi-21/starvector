"""Deterministic fake generalizer for tests.

Fills the Generalizer slot of docs/specs/fuse-and-validate.md section
8.2 offline. The rule is pure text: the broader phrase is the word
"general" plus the element's last word, which is a p02 fixed point
when the input's last word is one (lowercase, no leading "the" or
"a", singular). Deterministic, no network, no stored data.
"""

from collections.abc import Sequence

from core.canonical import canonical_json, sha256_hex

_RULE = "head-noun-v1"


class FakeGeneralizer:
    """Generalizer that runs the head-noun rule."""

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake generalizer parameters."""
        return sha256_hex(canonical_json({
            "provider": "fake-generalizer",
            "rule": _RULE,
        }))

    def generalize(self, texts: Sequence[str]) -> list[str]:
        """One broader phrase for each element string, index-aligned."""
        phrases = []
        for text in texts:
            if not text.strip():
                raise ValueError("element strings must be non-empty")
            phrases.append("general " + text.split()[-1])
        return phrases
