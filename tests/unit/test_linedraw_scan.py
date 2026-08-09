"""Unit tests for the pure parts of the line-drawer parameter scan."""

import numpy as np
from PIL import Image
from io import BytesIO

from core.lineart import render_canonical
from validation.linedraw_scan import (SCAN_CELLS, ScanCell, build_sheet_html,
                                      cell_label, control_image_ids,
                                      ink_fraction, worst_pair_keys)


def test_the_d1_grid_is_pinned() -> None:
    assert len(SCAN_CELLS) == 10
    assert ScanCell(0.50, 512, 10) in SCAN_CELLS      # the control
    assert ScanCell(0.30, 1024, 10) in SCAN_CELLS
    assert ScanCell(0.40, 512, 5) in SCAN_CELLS       # the pruning cell
    assert cell_label(ScanCell(0.40, 768, 10)) == "t0.40 r768 s10"


def test_controls_are_seeded_and_out_of_the_group() -> None:
    image_ids = tuple(f"{i:03d}" + "a" * 61 for i in range(12))
    group_ids = tuple([image_ids[0]] * 4 + list(image_ids[4:]))
    first = control_image_ids(image_ids, group_ids, image_ids[0], count=3)
    again = control_image_ids(image_ids, group_ids, image_ids[0], count=3)
    assert first == again
    assert len(first) == 3
    assert not set(first) & set(image_ids[:4])


def test_worst_pair_keys_sort_worst_first() -> None:
    rows = [
        {"pair_key": "a/1", "target_rank": 5},
        {"pair_key": "b/2", "target_rank": 300},
        {"pair_key": "c/3", "target_rank": 120},
    ]
    assert worst_pair_keys(rows, count=2) == ("b/2", "c/3")


def test_ink_fraction_counts_dark_pixels() -> None:
    mask = np.zeros((64, 64), dtype=np.bool_)
    mask[10, :] = True
    drawing = render_canonical(mask, 64, 1)
    assert ink_fraction(drawing) == 64 / (64 * 64)


def test_the_sheet_holds_each_row_and_header() -> None:
    html = build_sheet_html(
        ["photo", "t0.40 r768 s10"],
        [("group", "abc", ["data:image/png;base64,x"] * 2),
         ("control", "def", ["data:image/png;base64,y"] * 2)])
    assert "t0.40 r768 s10" in html
    assert html.count("<tr>") == 3
    assert 'class="kind group"' in html
    assert "def" in html
