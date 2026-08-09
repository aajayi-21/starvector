"""Shared boundary validation for sketch-pair adapters.

Each adapter applies these rules to each record it yields (spec P2
section 8): validation at the boundary, and code after it assumes
checked input (CLAUDE.md section 3).
"""

from providers.protocols import SketchPair


def check_sketch_pair(pair: SketchPair) -> None:
    """Raises when one pair does not obey the SketchPair rules.

    Rules: a non-empty pair_key and photo_bytes, one filled sketch
    field of the two, a minimum of one stroke with one point each —
    a dot is a permitted stroke, as in Layer 0 — and each point
    component in the closed interval [0, 1] (D2).
    """
    if not pair.pair_key:
        raise ValueError("pair_key must not be empty")
    if not pair.photo_bytes:
        raise ValueError(f"{pair.pair_key}: photo_bytes must not be empty")
    has_strokes = pair.sketch_strokes is not None
    has_bytes = pair.sketch_bytes is not None
    if has_strokes == has_bytes:
        raise ValueError(
            f"{pair.pair_key}: one of sketch_strokes and sketch_bytes "
            "must be filled")
    if pair.sketch_strokes is not None:
        if not pair.sketch_strokes:
            raise ValueError(
                f"{pair.pair_key}: sketch_strokes must not be empty")
        for stroke in pair.sketch_strokes:
            if not stroke:
                raise ValueError(
                    f"{pair.pair_key}: a stroke with no points")
            for x, y in stroke:
                if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                    raise ValueError(
                        f"{pair.pair_key}: point ({x}, {y}) is not in "
                        "the unit square")
    if pair.sketch_bytes is not None and not pair.sketch_bytes:
        raise ValueError(
            f"{pair.pair_key}: sketch_bytes must not be empty")
