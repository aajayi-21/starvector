"""The username rules (spec A2 section 4).

Pure functions of strings: the sign-up rule, the reserved table, and
the folded shape that makes one name of two names that look the same.
The store rule for a player name is wider and stays as it is: a record
of an earlier date with a longer name is legal (spec A2 section 4.1).
"""

import re

# Decision D1 of spec A2.
USERNAME_MIN = 3
USERNAME_MAX = 20

# Decision D2 of spec A2: the words for the operator and the app, the
# path words, and two words that code writes for "no value".
RESERVED_NAMES = frozenset({
    "admin", "operator", "moderator", "staff", "support", "system",
    "root", "starvector",
    "api", "join", "me", "dev",
    "null", "undefined",
})

NAME_RULE = "name-rule"
NAME_RESERVED = "name-reserved"

# The first character is a letter, the last character is not a hyphen,
# and a hyphen has no hyphen after it.
_USERNAME_SHAPE = re.compile(r"[a-z](?:-?[a-z0-9])*")

_CAPITALS = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                          "abcdefghijklmnopqrstuvwxyz")
_FOLD = str.maketrans({"-": None, "0": "o", "1": "l"})


def normalize_username(value: object) -> str | None:
    """A typed username with its ASCII capitals as small letters, or
    None for a value that is not text.

    The map covers A to Z alone. str.lower also turns some characters
    of other scripts into ASCII letters, and such a character must
    stay illegal.
    """
    if not isinstance(value, str):
        return None
    return value.translate(_CAPITALS)


def folded_name(name: str) -> str:
    """The folded shape of one name (spec A2 section 4.2).

    Each hyphen goes, 0 becomes o, and 1 becomes l. Two names with one
    folded shape look the same on a board, thus they are one name.
    """
    return name.translate(_FOLD)


_RESERVED_FOLDED = frozenset(folded_name(name) for name in RESERVED_NAMES)


def username_refusal(name: str) -> str | None:
    """The cause that refuses one username at sign-up, or None.

    name is the output of normalize_username. The reserved check reads
    the folded shape, thus r00t and ad-min are refused with root and
    admin.
    """
    if not USERNAME_MIN <= len(name) <= USERNAME_MAX:
        return NAME_RULE
    if not _USERNAME_SHAPE.fullmatch(name):
        return NAME_RULE
    if folded_name(name) in _RESERVED_FOLDED:
        return NAME_RESERVED
    return None
