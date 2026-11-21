"""The sketch of a stored send, as a second person gets it.

Spec: SS1 (in docs/specs/send-then-see.md) sections 5 and 7.2. Pure
functions of a stored wire record and of plain numbers - no file read,
no clock read. The server reads the store and gives the record.

The rule of section 5: a second person gets the points and the color
of each stroke, and nothing more. A wire record also holds words, part
labels, group identifiers, relation names, and notes. Each of those is
text of the player, and no function here gives one of them.
"""

import re
from collections.abc import Mapping, Sequence

# The stored shape of a stroke color (spec C1): a lowercase #rrggbb.
_COLOR_RULE = re.compile(r"#[0-9a-f]{6}")

# The marks of an entry of the sends of a day (spec SS1 section 7.2).
SKETCH = "sketch"
WORDS_ONLY = "words-only"
WITHHELD = "withheld"
AFTER_REVEAL = "after-reveal"


class SketchError(ValueError):
    """A stored record does not have the shape of the wire record."""


def _point_of(entry: object) -> list:
    """The x and the y of one stored point, as the store has them.

    A stored point can hold more numbers after the two coordinates.
    They do not go out.
    """
    if (not isinstance(entry, list) or len(entry) < 2
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   for value in entry[:2])):
        raise SketchError(f"a stored point is not two numbers: {entry!r}")
    return [entry[0], entry[1]]


def sketch_of(record: object) -> list[dict]:
    """The strokes of one stored wire record, and no text of it.

    Each stroke of the answer is a mapping with `points`, a sequence
    of [x, y] in the range 0 to 1, and with `color` when the stored
    stroke has one. The answer holds no other key: no `group_id`, no
    word, no label, no relation, and no note.

    Raises SketchError when the record is not the stored shape. A
    stored send went through Layer 0, thus a bad shape here is damage
    to the store, and the caller must not show a part of it.
    """
    if not isinstance(record, Mapping):
        raise SketchError("a stored record is not an object")
    strokes = record.get("canvas_strokes")
    if not isinstance(strokes, list):
        raise SketchError("a stored record has no stroke sequence")
    sketch = []
    for stroke in strokes:
        if (not isinstance(stroke, Mapping)
                or not isinstance(stroke.get("points"), list)):
            raise SketchError("a stored stroke has no point sequence")
        entry: dict = {"points": [_point_of(point)
                                  for point in stroke["points"]]}
        color = stroke.get("color")
        if color is not None:
            if not isinstance(color, str) or not _COLOR_RULE.fullmatch(color):
                raise SketchError(f"a stored color is not #rrggbb: {color!r}")
            entry["color"] = color
        sketch.append(entry)
    return sketch


def point_count(sketch: Sequence[Mapping]) -> int:
    """The number of points in one sketch."""
    return sum(len(stroke["points"]) for stroke in sketch)


def entry_state(*, has_strokes: bool, withheld: bool, shows: bool) -> str:
    """The mark of one entry of the sends of a day.

    The sequence of the checks is the rule. A withheld send says
    nothing more. A send that waits for the reveal does not say if it
    has a sketch. A send with no stroke has the words-only mark. Each
    other send shows its sketch.
    """
    if withheld:
        return WITHHELD
    if not shows:
        return AFTER_REVEAL
    return SKETCH if has_strokes else WORDS_ONLY


def page_has_room(*, taken: int, points: int, more: int,
                  entry_cap: int, point_cap: int) -> bool:
    """A page that holds `taken` entries can hold one more.

    `points` is the number of points in the page, and `more` is the
    number of points of the candidate entry. The first entry of a page
    is always in it, thus one large sketch does not stop the sequence.
    """
    if taken == 0:
        return True
    return taken < entry_cap and points + more <= point_cap
