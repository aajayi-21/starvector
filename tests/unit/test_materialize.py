"""Unit tests for the s02 pure parts in pool.curation.stages.materialize."""

from io import BytesIO

from PIL import Image

from pool.curation.config import ScreenSection
from pool.curation.stages.materialize import (
    DecodedImage,
    ScreenRejection,
    resolve_duplicate_bytes,
    screen_decoded,
)

_SCREEN = ScreenSection(min_short_side=512, min_aspect=0.5, max_aspect=2.0)


def _png_bytes(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (120, 60, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_decodable_image_in_range_is_a_decoded_image() -> None:
    result = screen_decoded(_png_bytes(512, 512), _SCREEN)
    assert result == DecodedImage(width=512, height=512, image_format="PNG")


def test_short_side_below_the_limit_gets_rejected() -> None:
    result = screen_decoded(_png_bytes(511, 600), _SCREEN)
    assert result == ScreenRejection(reason="resolution", measured=511.0, detail="")


def test_aspect_outside_the_range_gets_rejected() -> None:
    # min_short_side 500 keeps the R2 check quiet for the 1200 x 500 image.
    screen = ScreenSection(min_short_side=500, min_aspect=0.5, max_aspect=2.0)
    result = screen_decoded(_png_bytes(1200, 500), screen)
    assert result == ScreenRejection(reason="aspect", measured=2.4, detail="")


def test_bytes_that_do_not_decode_get_a_decode_error() -> None:
    result = screen_decoded(b"not an image", _SCREEN)
    assert isinstance(result, ScreenRejection)
    assert result.reason == "decode-error"
    assert result.measured is None
    assert result.detail != ""


def test_duplicate_bytes_keeps_the_smallest_source_key() -> None:
    entries = [("b", "img1"), ("a", "img1"), ("c", "img2"), ("d", "img1")]
    result = resolve_duplicate_bytes(entries)
    assert result.kept == (("a", "img1"), ("c", "img2"))
    assert result.rejected == (("b", "a", "img1"), ("d", "a", "img1"))


def test_duplicate_resolution_does_not_depend_on_input_sequence() -> None:
    forward = resolve_duplicate_bytes([("a", "x"), ("b", "x"), ("c", "y")])
    backward = resolve_duplicate_bytes([("c", "y"), ("b", "x"), ("a", "x")])
    assert forward == backward
    assert forward.kept == (("a", "x"), ("c", "y"))
    assert forward.rejected == (("b", "a", "x"),)
