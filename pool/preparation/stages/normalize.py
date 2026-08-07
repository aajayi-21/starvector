"""Stage p02 element normalization. Pure string rules.

Spec: docs/specs/pool-preparation.md section 10, stage p02, and
decision D7 (rule table d7-v1). Architecture rule R4 names the steps:
lowercase, strip articles, singularize. The rules are deterministic
and versioned by the config hash - no model. The same rules apply to
atoms at scoring time, and agreement between the two sides matters
more than correct English plurals.
"""

import unicodedata

from pool.preparation.types import ElementResponse

_ARTICLES = ("a", "an", "the")
_SIBILANT_ENDINGS = ("s", "x", "z", "ch", "sh")


def _singularize(word: str) -> str:
    """Apply the d7-v1 rule table to the last word of an element.

    Words of 3 characters or fewer are kept unchanged. "-ies" becomes
    "-y". "-es" is dropped after "s", "x", "z", "ch", or "sh". A
    "-ss" ending is kept. In other cases one trailing "-s" is
    dropped. The "-ss" check comes before the plain "-s" rule.
    """
    if len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("es") and word[:-2].endswith(_SIBILANT_ENDINGS):
        return word[:-2]
    if word.endswith("ss"):
        return word
    if word.endswith("s"):
        return word[:-1]
    return word


def normalize_element(text: str) -> str:
    """Normalize one element string with the R4 rules.

    Steps, in sequence: Unicode NFC, lowercase, each internal
    whitespace run becomes one space and the ends are stripped, one
    leading "a", "an", or "the" is removed only when a word follows
    it, and the last word goes through the d7-v1 table. The output
    can be empty when the input holds no word. Normalization runs one
    time on each side - the pipeline applies it one time in p02, and
    the atom path must also apply it one time to raw text. A second
    run can decrease some sibilant-stem words again ("houses" gives
    "hous", and one more run gives "hou"), thus a stored normalized
    string must not go through this function again.
    """
    collapsed = " ".join(unicodedata.normalize("NFC", text).lower().split())
    if not collapsed:
        return ""
    words = collapsed.split(" ")
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    words[-1] = _singularize(words[-1])
    return " ".join(words)


def normalize_flatten(response: ElementResponse) -> tuple[str, ...]:
    """Flatten one element response in the D8 field sequence.

    The sequence is the R2 field sequence - the ELEMENT_FIELDS
    constant. The fifth and sixth fields are plain strings and
    contribute one entry each.
    """
    return (
        *response.objects,
        *response.materials,
        *response.colors,
        *response.shapes,
        response.scale,
        response.setting,
        *response.ambience,
    )


def normalize_elements(response: ElementResponse) -> tuple[str, ...]:
    """The normalized, deduplicated, uncapped element sequence (p02).

    Flatten in the D8 sequence, normalize each entry, drop entries
    that normalization empties, and keep the first occurrence of a
    duplicated string.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for entry in normalize_flatten(response):
        normalized = normalize_element(entry)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        kept.append(normalized)
    return tuple(kept)
