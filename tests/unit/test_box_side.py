"""Unit tests for the p07 box side of the context loader (P4 §7)."""

import numpy as np
import pytest

from pipeline.context import ContextError, box_side

IDS = ("a" * 64, "b" * 64)
VOCABULARY = ("boat", "sky", "tower")
INCIDENCE = np.asarray([[2, 0, -1], [0, 1, 2]], dtype=np.int32)


def _rows(**overrides):
    rows = [
        {"image_id": IDS[0],
         "boxes": {"tower": [0.1, 0.1, 0.4, 0.4], "boat": None}},
        {"image_id": IDS[1],
         "boxes": {"boat": [0.5, 0.5, 0.9, 0.9],
                   "sky": [0.0, 0.0, 1.0, 1.0],
                   "tower": [0.2, 0.1, 0.3, 0.6]}},
    ]
    for position, row in overrides.items():
        rows[int(position)] = row
    return rows


def test_slot_alignment_follows_the_incidence_table() -> None:
    table, mask = box_side(_rows(), IDS, VOCABULARY, INCIDENCE)
    assert table.shape == (2, 3, 4) and mask.shape == (2, 3)
    # Image a: slot 0 is "tower", slot 1 is "boat" (null), slot 2 pads.
    assert mask[0].tolist() == [True, False, False]
    assert table[0, 0].tolist() == pytest.approx([0.1, 0.1, 0.4, 0.4])
    assert table[0, 1].tolist() == [0.0, 0.0, 0.0, 0.0]
    # Image b: all three slots hold boxes.
    assert mask[1].tolist() == [True, True, True]
    assert table[1, 1].tolist() == pytest.approx([0.0, 0.0, 1.0, 1.0])


def test_a_row_out_of_sequence_raises() -> None:
    rows = _rows()
    rows.reverse()
    with pytest.raises(ContextError, match="p00 sequence"):
        box_side(rows, IDS, VOCABULARY, INCIDENCE)


def test_a_key_set_that_differs_from_the_element_list_raises() -> None:
    rows = _rows(**{"0": {"image_id": IDS[0],
                          "boxes": {"tower": [0.1, 0.1, 0.4, 0.4]}}})
    with pytest.raises(ContextError, match="missing \\['boat'\\]"):
        box_side(rows, IDS, VOCABULARY, INCIDENCE)


def test_a_degenerate_box_raises() -> None:
    rows = _rows(**{"0": {"image_id": IDS[0],
                          "boxes": {"tower": [0.4, 0.1, 0.4, 0.5],
                                    "boat": None}}})
    with pytest.raises(ContextError, match="positive extent"):
        box_side(rows, IDS, VOCABULARY, INCIDENCE)


def test_a_non_numeric_box_raises() -> None:
    rows = _rows(**{"0": {"image_id": IDS[0],
                          "boxes": {"tower": [0.1, 0.1, 0.4, True],
                                    "boat": None}}})
    with pytest.raises(ContextError, match="four numbers or null"):
        box_side(rows, IDS, VOCABULARY, INCIDENCE)


def test_a_row_count_mismatch_raises() -> None:
    with pytest.raises(ContextError, match="do not agree"):
        box_side(_rows()[:1], IDS, VOCABULARY, INCIDENCE)
