"""Stage p02 element normalization. Pure string rules.

Spec: docs/specs/pool-preparation.md section 10, stage p02, and
decision D7 (rule tables d7-v1 and d8-v1). Architecture rule R4 names
the steps: lowercase, strip articles, singularize. The rules are
deterministic and versioned by the config hash - no model. They apply
to pool elements alone. The encoder reads atoms as the player wrote
them (docs/specs/element-channel.md section 15), thus a mangled pool
string has no matching atom string, and the encoder reads a word that
is not a word.

d7-v1 stays for each stored lineage, because a stored day rescores
through it. d8-v1 is the rule for each new lineage. It was written from
the 225 singularizations of the dev-wit-002 element lists.
"""

import unicodedata

from pool.preparation.types import ElementResponse

_ARTICLES = ("a", "an", "the")
_SIBILANT_ENDINGS = ("s", "x", "z", "ch", "sh")


# d8-v1: singular words that end in "s" and have no shared ending.
_D8_SINGULAR_WORDS = frozenset({
    "alias", "atlas", "bias", "canvas", "christmas", "lens", "pampas",
})
_D8_SINGULAR_ENDINGS = ("ss", "ous", "us", "is")
# d8-v1: plurals in "-ses" that drop "-es", not "-s". Other "-ses" words
# have the shape of "horses", and they drop "-s".
_D8_ES_AFTER_S = frozenset({
    "atlases", "bonuses", "buses", "cactuses", "campuses", "canvases",
    "circuses", "gases", "irises", "lenses", "octopuses", "statuses",
    "viruses", "walruses",
})
# d8-v1: "-ies" plurals with a singular in "-ie".
_D8_IE_WORDS = frozenset({
    "calories", "cookies", "movies", "pies", "selfies", "ties", "zombies",
})
_D8_IRREGULAR = {
    "bookshelves": "bookshelf", "calves": "calf", "knives": "knife",
    "leaves": "leaf", "loaves": "loaf", "scarves": "scarf",
    "shelves": "shelf", "wolves": "wolf",
}


def _singularize_d8(word: str) -> str:
    """Apply the d8-v1 rule table to the last word of an element.

    Words of 3 characters or fewer are kept unchanged, and the irregular
    table applies first. The singular word set and the endings "-ss",
    "-ous", "-us", and "-is" are kept: "spacious", "campus", and "dais"
    are singular. The plural "taxis" also stays, which is a split
    vocabulary entry and not a word the encoder cannot read. "-ies"
    becomes "-y" for each word not in the "-ie" set. "-es" is dropped
    after "x", "ch", or "sh", after "ss", after "tz", and for the "-ses"
    word set. In other cases one trailing "-s" is dropped.
    """
    if len(word) <= 3:
        return word
    if word in _D8_IRREGULAR:
        return _D8_IRREGULAR[word]
    if word in _D8_SINGULAR_WORDS or word.endswith(_D8_SINGULAR_ENDINGS):
        return word
    if word.endswith("ies"):
        return word[:-1] if word in _D8_IE_WORDS else word[:-3] + "y"
    if word.endswith("es"):
        stem = word[:-2]
        if (stem.endswith(("x", "ch", "sh", "ss", "tz"))
                or word in _D8_ES_AFTER_S):
            return stem
    if word.endswith("s"):
        return word[:-1]
    return word


def _singularize_d7(word: str) -> str:
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


def _singularize(word: str, rule: str) -> str:
    match rule:
        case "d7-v1":
            return _singularize_d7(word)
        case "d8-v1":
            return _singularize_d8(word)
        case unknown:
            raise ValueError(f"unknown normalize rule: {unknown}")


def normalize_element(text: str, rule: str) -> str:
    """Normalize one element string with the R4 rules.

    Steps, in sequence: Unicode NFC, lowercase, each internal
    whitespace run becomes one space and the ends are stripped, one
    leading "a", "an", or "the" is removed only when a word follows
    it, and the last word goes through the d7-v1 table. The output
    can be empty when the input holds no word. Normalization runs one
    time on each side - the pipeline applies it one time in p02, and
    the atom path must also apply it one time to raw text. A second
    run can decrease some sibilant-stem words again (with d7-v1
    "houses" gives "hous", and one more run gives "hou"), thus a stored
    normalized string must not go through this function again.
    """
    collapsed = " ".join(unicodedata.normalize("NFC", text).lower().split())
    if not collapsed:
        return ""
    words = collapsed.split(" ")
    if len(words) > 1 and words[0] in _ARTICLES:
        words = words[1:]
    words[-1] = _singularize(words[-1], rule)
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


def normalize_elements(response: ElementResponse, rule: str) -> tuple[str, ...]:
    """The normalized, deduplicated, uncapped element sequence (p02).

    Flatten in the D8 sequence, normalize each entry, drop entries
    that normalization empties, and keep the first occurrence of a
    duplicated string.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for entry in normalize_flatten(response):
        normalized = normalize_element(entry, rule)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        kept.append(normalized)
    return tuple(kept)
