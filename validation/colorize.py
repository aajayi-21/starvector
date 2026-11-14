"""Seeded stroke colors for the V2c gate (spec C1 section 6).

Pure: one record in, a colorized deep copy out, with the color of
each stroke a hash of the seed, the pair key, and the stroke index.
"""

import copy

from core.canonical import JsonValue, sha256_hex

# The seven non-ink palette values (spec C1 section 5, the set of
# 2026-08-14): red, orange, yellow, green, blue, purple, teal. The web
# interface sends these values (web/src/sketch/palette.ts), thus the
# gate measures the colors that a player can send.
PALETTE: tuple[str, ...] = ("#bf616a", "#d08770", "#ebcb8b", "#a3be8c",
                            "#81a1c1", "#b48ead", "#8fbcbb")


def colorized_record(record: JsonValue, seed: int,
                     pair_key: str) -> JsonValue:
    """A deep copy of one wire record with a color on each stroke.

    The color of stroke i is PALETTE[h % 7] with h the first eight
    hex digits of sha256("v2c:{seed}:{pair_key}:{i}") — the same
    inputs give the same record, and no other field moves.
    """
    result = copy.deepcopy(record)
    for index, stroke in enumerate(result["canvas_strokes"]):
        value = int(sha256_hex(f"v2c:{seed}:{pair_key}:{index}")[:8], 16)
        stroke["color"] = PALETTE[value % len(PALETTE)]
    return result
