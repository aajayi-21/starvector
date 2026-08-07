"""Unit tests for the s08 pure functions: sample, thumbnail, sheet."""

import base64
from io import BytesIO

import pytest
from PIL import Image

from pool.curation.stages.review import (
    ReviewEntry,
    contact_sheet_html,
    select_review_sample,
    thumbnail_png,
)


def _image_ids(count: int) -> list[str]:
    return sorted(f"{index:064x}" for index in range(count))


def _png_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (200, 30, 90))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _entries() -> list[ReviewEntry]:
    thumb = thumbnail_png(_png_bytes(64, 48), max_side=32)
    encoded = base64.b64encode(thumb).decode("ascii")
    return [
        ReviewEntry(
            image_id="aa" * 32, caption="A stone bridge", thumbnail_png_base64=encoded
        ),
        ReviewEntry(
            image_id="bb" * 32,
            caption="<b>caption</b> & more",
            thumbnail_png_base64=encoded,
        ),
    ]


def test_sample_keeps_all_survivors_when_pool_is_smaller() -> None:
    ids = _image_ids(150)
    sample = select_review_sample(ids, sample_size=200, review_seed=7)
    assert sample == tuple(ids)


def test_sample_count_is_capped_at_sample_size() -> None:
    ids = _image_ids(250)
    sample = select_review_sample(ids, sample_size=200, review_seed=7)
    assert len(sample) == 200
    assert len(set(sample)) == 200
    assert set(sample) <= set(ids)


def test_sample_output_is_sorted_ascending() -> None:
    ids = _image_ids(250)
    sample = select_review_sample(ids, sample_size=200, review_seed=11)
    assert list(sample) == sorted(sample)


def test_same_seed_gives_the_same_sample() -> None:
    ids = _image_ids(250)
    first = select_review_sample(ids, sample_size=200, review_seed=3)
    second = select_review_sample(ids, sample_size=200, review_seed=3)
    assert first == second


def test_different_seed_gives_a_different_sample() -> None:
    ids = _image_ids(1000)
    first = select_review_sample(ids, sample_size=200, review_seed=3)
    second = select_review_sample(ids, sample_size=200, review_seed=4)
    assert first != second


def test_unsorted_input_raises() -> None:
    with pytest.raises(ValueError):
        select_review_sample(["b", "a"], sample_size=2, review_seed=0)


def test_thumbnail_decodes_and_fits_max_side() -> None:
    thumb = thumbnail_png(_png_bytes(800, 600), max_side=128)
    with Image.open(BytesIO(thumb)) as decoded:
        assert decoded.format == "PNG"
        assert max(decoded.size) <= 128


def test_thumbnail_of_tall_image_fits_max_side() -> None:
    thumb = thumbnail_png(_png_bytes(300, 900), max_side=100)
    with Image.open(BytesIO(thumb)) as decoded:
        assert max(decoded.size) <= 100


def test_thumbnail_is_deterministic() -> None:
    source = _png_bytes(640, 480)
    assert thumbnail_png(source, max_side=100) == thumbnail_png(source, max_side=100)


def test_contact_sheet_shows_ids_and_captions() -> None:
    sheet = contact_sheet_html(_entries(), label="dev-wit s08")
    assert "dev-wit s08" in sheet
    assert "aa" * 32 in sheet
    assert "bb" * 32 in sheet
    assert "A stone bridge" in sheet


def test_contact_sheet_neutralizes_markup_in_captions() -> None:
    sheet = contact_sheet_html(_entries(), label="s08")
    assert "<b>caption</b>" not in sheet
    assert "&lt;b&gt;caption&lt;/b&gt;" in sheet
    assert "&amp; more" in sheet


def test_contact_sheet_embeds_data_uris_and_no_external_hosts() -> None:
    sheet = contact_sheet_html(_entries(), label="s08")
    assert "data:image/png;base64," in sheet
    assert "http://" not in sheet
    assert "https://" not in sheet


def test_contact_sheet_is_deterministic() -> None:
    entries = _entries()
    assert contact_sheet_html(entries, "x") == contact_sheet_html(entries, "x")
