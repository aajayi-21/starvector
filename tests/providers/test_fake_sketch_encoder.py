"""Marker geometry through the production render and back.

The style bridge instrument: strokes from the fake pair source go
through the production render, and the fake encoder must read the
family back from the pixels alone.
"""

import numpy as np
import pytest

from core.intake import render_strokes
from providers.fake import markers
from providers.fake.sketch_encoder import FakeSketchEncoder
from providers.fake.vectors import _seed_from, _unit_gaussian

CANVAS = 512
WIDTH = 3
DIMENSION = 32


def _content_strokes(seed: int):
    rng = np.random.default_rng(seed)
    strokes = []
    for _ in range(2):
        xs = rng.uniform(0.0, 1.0, 5)
        ys = rng.uniform(0.0, markers.CONTENT_MAX_Y, 5)
        strokes.append(tuple((float(x), float(y)) for x, y in zip(xs, ys)))
    return tuple(strokes)


@pytest.mark.parametrize("family_id", [0, 1, 42, 85, 127])
def test_the_family_survives_the_production_render(family_id: int) -> None:
    strokes = markers.encode_family_strokes(family_id) + _content_strokes(7)
    png = render_strokes(strokes, CANVAS, WIDTH)
    assert markers.decode_family(png) == family_id


@pytest.mark.parametrize("line_width", [1, 3, 5, 9])
def test_the_family_survives_each_line_width(line_width: int) -> None:
    png = render_strokes(markers.encode_family_strokes(85), CANVAS,
                         line_width)
    assert markers.decode_family(png) == 85


def test_the_encoded_vector_lands_on_the_family_base() -> None:
    png = render_strokes(markers.encode_family_strokes(85) +
                         _content_strokes(3), CANVAS, WIDTH)
    vector = FakeSketchEncoder(DIMENSION).encode_images([png])[0]
    base = _unit_gaussian(
        _seed_from("family:" + markers.family_name(85)), DIMENSION)
    assert float(vector @ base) > 0.99


def test_a_render_without_a_sync_stroke_decodes_to_none() -> None:
    png = render_strokes(_content_strokes(5), CANVAS, WIDTH)
    assert markers.decode_family(png) is None
    vector = FakeSketchEncoder(DIMENSION).encode_images([png])[0]
    seeded = _unit_gaussian(_seed_from(png), DIMENSION)
    assert vector == pytest.approx(seeded.astype(np.float32), abs=1e-6)


def test_a_small_canvas_raises() -> None:
    png = render_strokes(markers.encode_family_strokes(1), 64, 1)
    with pytest.raises(ValueError, match="below the marker minimum"):
        markers.decode_family(png)


def test_the_output_is_unit_norm_float32() -> None:
    pngs = [render_strokes(markers.encode_family_strokes(i), CANVAS, WIDTH)
            for i in (0, 3)]
    vectors = FakeSketchEncoder(DIMENSION).encode_images(pngs)
    assert vectors.shape == (2, DIMENSION)
    assert vectors.dtype == np.float32
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1.0, 1.0])


def test_empty_input_gives_an_empty_stack() -> None:
    assert FakeSketchEncoder(DIMENSION).encode_images([]).shape \
        == (0, DIMENSION)


def test_the_hash_differs_from_the_fake_image_encoder() -> None:
    from providers.fake.encoder import FakeImageEncoder

    assert FakeSketchEncoder(DIMENSION).config_hash \
        != FakeImageEncoder(DIMENSION).config_hash


def test_a_family_identifier_off_the_range_raises() -> None:
    with pytest.raises(ValueError, match="family_id"):
        markers.encode_family_strokes(128)
