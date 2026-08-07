"""Tests for the Hugging Face row mapping. Offline only.

The corpus adapter itself needs the network, thus these tests cover
only the pure row mapping and the module import.
"""

from typing import Any

import pytest

import providers.corpora.huggingface as hf_module
from providers.corpora.huggingface import HuggingFaceColumns, row_to_source_record

COLUMNS = HuggingFaceColumns(
    source_key="image_url",
    claimed_width="original_width",
    claimed_height="original_height",
    captions=("caption_attribution_description",),
    attribution=("image_url", "metadata_url", "caption_attribution_description"),
)

LICENSE_NOTE = "CC BY-SA 4.0"

IMAGE_URL = "https://upload.wikimedia.org/wikipedia/commons/b/bc/A.jpg"


def _full_row() -> dict[str, Any]:
    return {
        "image_url": IMAGE_URL,
        "original_width": 4000,
        "original_height": 3000,
        "caption_attribution_description": "A canyon at dawn",
        "metadata_url": "http://commons.wikimedia.org/wiki/File:A.jpg",
    }


def test_module_import_stays_light() -> None:
    # The heavy hub libraries load in method bodies only.
    assert hasattr(hf_module, "HuggingFaceCorpus")
    assert "datasets" not in vars(hf_module)
    assert "huggingface_hub" not in vars(hf_module)


def test_full_row_maps_all_fields() -> None:
    record = row_to_source_record(_full_row(), COLUMNS, LICENSE_NOTE)
    assert record.source_key == IMAGE_URL
    assert record.claimed_width == 4000
    assert record.claimed_height == 3000
    assert record.captions == ("A canyon at dawn",)
    assert record.attribution == {
        "image_url": IMAGE_URL,
        "metadata_url": "http://commons.wikimedia.org/wiki/File:A.jpg",
        "caption_attribution_description": "A canyon at dawn",
        "license": LICENSE_NOTE,
    }


def test_missing_caption_column_gives_empty_captions() -> None:
    row = _full_row()
    del row["caption_attribution_description"]
    record = row_to_source_record(row, COLUMNS, LICENSE_NOTE)
    assert record.captions == ()
    assert "caption_attribution_description" not in record.attribution


def test_null_dimensions_become_none() -> None:
    row = _full_row()
    row["original_width"] = None
    row["original_height"] = None
    record = row_to_source_record(row, COLUMNS, LICENSE_NOTE)
    assert record.claimed_width is None
    assert record.claimed_height is None


def test_missing_source_key_raises() -> None:
    row = _full_row()
    del row["image_url"]
    with pytest.raises(ValueError):
        row_to_source_record(row, COLUMNS, LICENSE_NOTE)


def test_empty_source_key_raises() -> None:
    row = _full_row()
    row["image_url"] = ""
    with pytest.raises(ValueError):
        row_to_source_record(row, COLUMNS, LICENSE_NOTE)


def test_attribution_skips_empty_values_and_carries_license() -> None:
    row = _full_row()
    row["metadata_url"] = ""
    record = row_to_source_record(row, COLUMNS, LICENSE_NOTE)
    assert "metadata_url" not in record.attribution
    assert record.attribution["license"] == LICENSE_NOTE
