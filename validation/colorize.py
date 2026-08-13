"""Seeded stroke colors for the V2c gate (spec C1 section 6).

Pure: one record in, a colorized deep copy out, with the color of
each stroke a hash of the seed, the pair key, and the stroke index.
"""

import copy

from core.canonical import JsonValue, sha256_hex

# The seven non-ink palette values (spec C1 section 5).
PALETTE: tuple[str, ...] = ("#c5221f", "#e8710a", "#f0b429", "#1b6b3a",
                            "#1a73e8", "#7a4ec9", "#795548")


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
