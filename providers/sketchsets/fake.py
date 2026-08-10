"""Deterministic fake sketch-pair source for tests.

Fills the SketchPairSource slot of docs/specs/scoring-path.md
section 8. Each pair scripts a shared family: the photograph carries
the embed_family PNG chunk (the FakeLineDrawer copies it through to
the drawing, and FakeImageEncoder reads it), and the sketch carries
the marker strokes of providers/fake/markers.py (FakeSketchEncoder
reads them from the rendered pixels). Thus the V1 harness gets a
positive signal offline, through the full production path.
"""

from collections.abc import Iterator
from io import BytesIO

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from core.canonical import canonical_json, sha256_hex
from core.types import StrokePath
from providers.fake import markers
from providers.fake.vectors import _seed_from
from providers.protocols import SketchPair, SketchsetIdentity
from providers.sketchsets.pairs import check_sketch_pair

# Family identifiers are one bit-field of seven bits (markers.BIT_YS),
# thus a fake set holds at most 128 pairs with one family each.
_MAX_PAIRS = 128

_PHOTO_SIDE = 64

# Content strokes: point count for each seeded polyline.
_CONTENT_POINTS = 5
_CONTENT_STROKES = 2

# The scripted element and description rule (spec P3 decision D6).
# Each word is a p02 fixed point: lowercase, one space between words,
# no leading "a", "an", or "the", and a last word the d7-v1 table keeps
# unchanged. The pair number keeps one pair's elements apart from the
# elements of each other pair, thus a description matches its own
# photograph and nothing else.
_ELEMENT_RULE = "tagged-words-v1"
_OBJECT_WORDS = ("tower", "boat", "lantern")
_MATERIAL_WORD = "stone"
_COLOR_WORD = "amber"
_SHAPE_WORD = "arch"
_SCALE_WORD = "wide"
_SETTING_WORD = "harbor"
_AMBIENCE_WORD = "quiet"

# The description names three of the photograph's elements and one
# word that is in no element list. A player submission holds some
# words that name nothing too.
_DESCRIBED_WORDS = (_OBJECT_WORDS[0], _OBJECT_WORDS[1], _SETTING_WORD)
_NOISE_WORD = "drift"


class FakeSketchsetConfig:
    """Frozen parameters for one fake sketch set."""

    __slots__ = ("pair_count", "neardup_families")

    def __init__(self, pair_count: int,
                 neardup_families: tuple[str, ...] = ()) -> None:
        if not 1 <= pair_count <= _MAX_PAIRS:
            raise ValueError(
                f"pair_count must be in [1, {_MAX_PAIRS}], got {pair_count}")
        self.pair_count = pair_count
        self.neardup_families = neardup_families

    def as_json(self) -> dict:
        return {
            "provider": "fake-sketchset",
            "pair_count": self.pair_count,
            "neardup_families": list(self.neardup_families),
            "marker_rule": markers.MARKER_RULE,
            "element_rule": _ELEMENT_RULE,
        }


def _tagged(word: str, position: int) -> str:
    """One scripted element string for the pair at position."""
    return f"{word} {position:04d}"


def scripted_elements(position: int) -> dict[str, object]:
    """The seven R2 fields the photograph chunk scripts (D6).

    The FakeVlmDescriber reads this back through the p01 slot, thus
    the union element side of V1 runs the production path offline.
    """
    return {
        "objects": [_tagged(word, position) for word in _OBJECT_WORDS],
        "materials": [_tagged(_MATERIAL_WORD, position)],
        "colors": [_tagged(_COLOR_WORD, position)],
        "shapes": [_tagged(_SHAPE_WORD, position)],
        "scale": _tagged(_SCALE_WORD, position),
        "setting": _tagged(_SETTING_WORD, position),
        "ambience": [_tagged(_AMBIENCE_WORD, position)],
    }


def scripted_description(position: int) -> str:
    """The pair's written description, in the frozen paste shape.

    Comma-separated, thus the frozen Layer 1 paste rule makes one atom
    for each word group (D9). Three of the atoms name elements of this
    pair's photograph and one names nothing.
    """
    words = [_tagged(word, position) for word in _DESCRIBED_WORDS]
    words.append(_tagged(_NOISE_WORD, position))
    return ", ".join(words)


def _photo_png(pixel_key: str, chunks: dict[str, str]) -> bytes:
    """One seeded photograph PNG with text chunks."""
    rng = np.random.default_rng(_seed_from(pixel_key))
    base = rng.integers(0, 256, (_PHOTO_SIDE, _PHOTO_SIDE, 3), dtype=np.uint8)
    image = Image.fromarray(base, mode="RGB")
    info = PngInfo()
    for chunk_key, chunk_value in sorted(chunks.items()):
        info.add_text(chunk_key, chunk_value)
    buffer = BytesIO()
    image.save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def _content_strokes(pair_key: str) -> tuple[StrokePath, ...]:
    """Seeded polylines confined above the marker band."""
    rng = np.random.default_rng(_seed_from("content:" + pair_key))
    strokes = []
    for _ in range(_CONTENT_STROKES):
        xs = rng.uniform(0.0, 1.0, _CONTENT_POINTS)
        ys = rng.uniform(0.0, markers.CONTENT_MAX_Y, _CONTENT_POINTS)
        strokes.append(tuple((float(x), float(y)) for x, y in zip(xs, ys)))
    return tuple(strokes)


class FakeSketchPairSource:
    """Fake pair source with scripted family structure.

    Pair index i gets family i, the photograph chunk embed_family =
    family_name(i) with embed_jitter "dup", and the sketch marker
    strokes for i. For i below len(neardup_families) the photograph
    chunk is neardup_families[i] — that photograph becomes a scripted
    near-duplicate of pool images of that family, the instrument for
    the union-grouping invariant.

    The photograph also carries the fake_elements chunk and the pair
    carries a written description built from those same elements
    (D6). FakeTextEncoder seeds by string, thus a description word and
    the element it names share one vector, and the V1 text mode gets a
    positive signal offline through the production path.
    """

    def __init__(self, config: FakeSketchsetConfig) -> None:
        self._config = config
        self._bytes_retrieved = 0

    @property
    def identity(self) -> SketchsetIdentity:
        digest = sha256_hex(canonical_json(self._config.as_json()))
        return SketchsetIdentity(provider="fake", name="fake-sketchset",
                                 revision=digest[:40])

    @property
    def config_hash(self) -> str:
        return sha256_hex(canonical_json(self._config.as_json()))

    @property
    def bytes_retrieved(self) -> int:
        return self._bytes_retrieved

    def iter_pairs(self) -> Iterator[SketchPair]:
        for position in range(self._config.pair_count):
            pair_key = f"fake://pair/{position:04d}"
            if position < len(self._config.neardup_families):
                family = self._config.neardup_families[position]
            else:
                family = markers.family_name(position)
            photo = _photo_png(pair_key, {
                "embed_family": family,
                "embed_jitter": "dup",
                "fake_elements": canonical_json(scripted_elements(position)),
            })
            strokes = (markers.encode_family_strokes(position)
                       + _content_strokes(pair_key))
            pair = SketchPair(pair_key=pair_key, photo_bytes=photo,
                              sketch_strokes=strokes, sketch_bytes=None,
                              category=None,
                              text=scripted_description(position))
            check_sketch_pair(pair)
            self._bytes_retrieved += len(photo)
            yield pair
