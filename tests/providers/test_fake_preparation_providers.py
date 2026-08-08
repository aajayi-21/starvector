"""Tests for the fake describer, text encoder, line drawer, and box detector."""

from io import BytesIO

import numpy as np
import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from core.canonical import canonical_json, sha256_hex
from providers.fake.boxes import FakeElementBoxDetector
from providers.fake.chunks import read_fake_chunks
from providers.fake.classifier import FakeZeroShotImageClassifier
from providers.fake.describer import FakeVlmDescriber
from providers.fake.encoder import FakeImageEncoder
from providers.fake.estimators import FakeSalientObjectEstimator, FakeTextCoverageEstimator
from providers.fake.linedrawer import FakeLineDrawer
from providers.fake.sketch_encoder import FakeSketchEncoder
from providers.fake.text_encoder import FakeTextEncoder
from providers.protocols import Box, ElementResponse

DIMENSION = 256

RESPONSE_DOCUMENT = {
    "objects": ["barn", "silo", "fence"],
    "materials": ["wood", "steel", "stone"],
    "colors": ["red", "gray", "green"],
    "shapes": ["rectangular", "cylindrical"],
    "scale": "building-sized",
    "setting": "farmland",
    "ambience": ["calm", "rural", "open"],
}


def _png_with_chunks(chunks: dict[str, str]) -> bytes:
    info = PngInfo()
    for chunk_key, chunk_value in chunks.items():
        info.add_text(chunk_key, chunk_value)
    buffer = BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (16, 16), color=(120, 60, 30)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_describer_scripted_chunk_parses():
    image = _png_with_chunks({"fake_elements": canonical_json(RESPONSE_DOCUMENT)})
    responses = FakeVlmDescriber().describe_images([image])
    assert responses == [
        ElementResponse(
            objects=("barn", "silo", "fence"),
            materials=("wood", "steel", "stone"),
            colors=("red", "gray", "green"),
            shapes=("rectangular", "cylindrical"),
            scale="building-sized",
            setting="farmland",
            ambience=("calm", "rural", "open"),
        )
    ]


def test_describer_accepts_scripted_over_count():
    # The fake is the test instrument for D2 boundary fixtures: a
    # scripted 25-entry objects field comes through unchanged.
    document = dict(RESPONSE_DOCUMENT)
    document["objects"] = [f"object-{index}" for index in range(25)]
    image = _png_with_chunks({"fake_elements": canonical_json(document)})
    responses = FakeVlmDescriber().describe_images([image])
    assert len(responses[0].objects) == 25


def test_describer_missing_chunk_raises():
    with pytest.raises(ValueError, match="fake_elements chunk is missing"):
        FakeVlmDescriber().describe_images([_png_with_chunks({})])


def test_describer_jpeg_bytes_raise():
    with pytest.raises(ValueError, match="fake_elements chunk is missing"):
        FakeVlmDescriber().describe_images([_jpeg_bytes()])


def test_describer_error_chunk_raises_scripted_text():
    image = _png_with_chunks({"fake_describer_error": "scripted describer failure"})
    with pytest.raises(ValueError, match="scripted describer failure"):
        FakeVlmDescriber().describe_images([image])


def test_text_encoder_shape_dtype_unit_norm():
    vectors = FakeTextEncoder(DIMENSION).encode_texts(["red barn", "granite", "calm"])
    assert vectors.shape == (3, DIMENSION)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_text_encoder_determinism_and_input_sensitivity():
    vectors_a = FakeTextEncoder(DIMENSION).encode_texts(["red barn", "granite"])
    vectors_b = FakeTextEncoder(DIMENSION).encode_texts(["red barn", "granite"])
    assert np.array_equal(vectors_a, vectors_b)
    assert float(vectors_a[0] @ vectors_a[1]) < 0.9


def test_text_encoder_empty_input():
    vectors = FakeTextEncoder(DIMENSION).encode_texts([])
    assert vectors.shape == (0, DIMENSION)
    assert vectors.dtype == np.float32


def test_line_drawer_deterministic_png():
    image = _png_with_chunks({"embed_family": "fam-1"})
    drawings_a = FakeLineDrawer().draw_lines([image])
    drawings_b = FakeLineDrawer().draw_lines([image])
    assert drawings_a[0] == drawings_b[0]
    assert drawings_a[0].startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(drawings_a[0])) as decoded:
        assert decoded.size == (64, 64)
        assert decoded.mode == "L"


def test_line_drawer_different_inputs_give_different_bytes():
    image_a = _png_with_chunks({"embed_family": "fam-1"})
    image_b = _png_with_chunks({"embed_family": "fam-2"})
    drawings = FakeLineDrawer().draw_lines([image_a, image_b])
    assert drawings[0] != drawings[1]


def test_line_drawer_copies_chunks_and_records_source():
    # Stage p06 encodes the drawing bytes, thus the fake image encoder
    # must find the embed chunks on the drawing.
    image = _png_with_chunks({"embed_family": "fam-1", "embed_jitter": "dup"})
    drawing = FakeLineDrawer().draw_lines([image])[0]
    chunks = read_fake_chunks(drawing)
    assert chunks["embed_family"] == "fam-1"
    assert chunks["embed_jitter"] == "dup"
    assert chunks["fake_line_of"] == sha256_hex(image)


def test_line_drawer_jpeg_source_gets_digest_chunk_only():
    jpeg = _jpeg_bytes()
    drawing = FakeLineDrawer(canvas_size=32).draw_lines([jpeg])[0]
    chunks = read_fake_chunks(drawing)
    assert chunks == {"fake_line_of": sha256_hex(jpeg)}
    with Image.open(BytesIO(drawing)) as decoded:
        assert decoded.size == (32, 32)


def _assert_derived_box_limits(box: Box) -> None:
    assert 0.0 <= box.x_min <= 0.8
    assert 0.0 <= box.y_min <= 0.8
    assert 0.05 <= box.x_max - box.x_min <= 0.2
    assert 0.05 <= box.y_max - box.y_min <= 0.2
    assert box.x_max <= 1.0
    assert box.y_max <= 1.0


def test_box_detector_unscripted_boxes_deterministic_and_in_limits():
    image = _png_with_chunks({})
    results_a = FakeElementBoxDetector().detect_boxes([image], [("barn", "fence")])
    results_b = FakeElementBoxDetector().detect_boxes([image], [("barn", "fence")])
    assert results_a == results_b
    assert list(results_a[0]) == ["barn", "fence"]
    for box in results_a[0].values():
        assert isinstance(box, Box)
        _assert_derived_box_limits(box)
    assert results_a[0]["barn"] != results_a[0]["fence"]


def test_box_detector_scripted_null_and_override():
    scripted = {"barn": None, "fence": [0.1, 0.2, 0.5, 0.6]}
    image = _png_with_chunks({"fake_boxes": canonical_json(scripted)})
    results = FakeElementBoxDetector().detect_boxes([image], [("barn", "fence", "sky")])
    assert results[0]["barn"] is None
    # The scripted box wins against the hash-derived rule: the scripted
    # height 0.4 is not reachable by that rule.
    assert results[0]["fence"] == Box(0.1, 0.2, 0.5, 0.6)
    assert isinstance(results[0]["sky"], Box)
    _assert_derived_box_limits(results[0]["sky"])


def test_box_detector_scripted_invalid_geometry_raises():
    scripted = {"barn": [0.5, 0.2, 0.4, 0.6]}
    image = _png_with_chunks({"fake_boxes": canonical_json(scripted)})
    with pytest.raises(ValueError, match=f"image {sha256_hex(image)} element 'barn'"):
        FakeElementBoxDetector().detect_boxes([image], [("barn",)])


def test_box_detector_chunk_free_jpeg_path():
    results = FakeElementBoxDetector().detect_boxes([_jpeg_bytes()], [("barn",)])
    box = results[0]["barn"]
    assert isinstance(box, Box)
    _assert_derived_box_limits(box)


def test_box_detector_duplicate_query_elements_raise():
    image = _png_with_chunks({})
    with pytest.raises(ValueError, match="duplicate query elements"):
        FakeElementBoxDetector().detect_boxes([image], [("barn", "barn")])


def test_box_detector_length_mismatch_raises():
    image = _png_with_chunks({})
    with pytest.raises(ValueError, match="1 entries but element_lists has 2"):
        FakeElementBoxDetector().detect_boxes([image], [("barn",), ("fence",)])


def test_config_hashes_are_different_across_all_fakes():
    hashes = {
        FakeVlmDescriber().config_hash,
        FakeTextEncoder(DIMENSION).config_hash,
        FakeLineDrawer().config_hash,
        FakeElementBoxDetector().config_hash,
        FakeImageEncoder(DIMENSION).config_hash,
        FakeZeroShotImageClassifier().config_hash,
        FakeTextCoverageEstimator().config_hash,
        FakeSalientObjectEstimator().config_hash,
        FakeSketchEncoder(DIMENSION).config_hash,
    }
    assert len(hashes) == 9
    assert all(len(value) == 64 for value in hashes)
    assert FakeTextEncoder(128).config_hash != FakeTextEncoder(256).config_hash
    assert FakeSketchEncoder(128).config_hash != FakeSketchEncoder(256).config_hash
    assert FakeLineDrawer(32).config_hash != FakeLineDrawer(64).config_hash
