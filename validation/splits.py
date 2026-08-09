"""Hash-based disjoint dataset splits (spec P2 decision D8).

The P1a s00 sampling rule, applied three ways: each pair key maps to a
fraction in [0, 1), and the three half-open ranges give the
background, V1, and V2 sets. Deterministic, disjoint by construction,
and free of enumeration-sequence effects. Pure functions only.
"""

from core.canonical import sha256_hex
from pipeline.config import SplitFractionsSection

SPLIT_NAMES: tuple[str, ...] = ("background", "v1", "v2")


def split_fraction(split_salt: str, pair_key: str) -> float:
    """The sampling fraction of one pair key, in [0, 1)."""
    return int(sha256_hex(split_salt + pair_key)[:16], 16) / 2.0**64


def split_of(split_salt: str, pair_key: str,
             fractions: SplitFractionsSection) -> str | None:
    """The split name for one pair key, or None in the tail.

    Ranges (D8): background [0, b), v1 [b, b + v1), v2
    [b + v1, b + v1 + v2). With fractions that sum below 1.0, keys in
    the tail belong to no split.
    """
    value = split_fraction(split_salt, pair_key)
    if value < fractions.background:
        return "background"
    if value < fractions.background + fractions.v1:
        return "v1"
    if value < fractions.background + fractions.v1 + fractions.v2:
        return "v2"
    return None


def selection_key(split_salt: str, pair_key: str) -> tuple[float, str]:
    """The deterministic ranking for selection from a split.

    Sort ascending by the sampling fraction, then by pair key — the
    same quantity the split was made with, thus the selection carries
    no bias (the P1a s02 argument).
    """
    return (split_fraction(split_salt, pair_key), pair_key)


def select_keys(pair_keys: list[str], split_salt: str,
                fractions: SplitFractionsSection, split_name: str,
                count: int) -> list[str]:
    """The first count members of one split, in selection ranking.

    Fewer members than count raises — a short split must stop the
    harness, not shrink it (spec section 15).
    """
    if split_name not in SPLIT_NAMES:
        raise ValueError(f"unknown split name: {split_name!r}")
    members = [key for key in pair_keys
               if split_of(split_salt, key, fractions) == split_name]
    members.sort(key=lambda key: selection_key(split_salt, key))
    if len(members) < count:
        raise ValueError(
            f"split {split_name!r} holds {len(members)} pairs, "
            f"{count} requested")
    return members[:count]
