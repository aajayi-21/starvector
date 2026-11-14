"""Unit tests for the synthetic rows that Layer 0 admits (spec P4 §17a).

A relation level draws rectangles along the element boxes. Two small
boxes give less ink than the min-ink gate, and Layer 0 refuses that
record. The harness removes it from the trial set and counts it.
"""

import pytest

from core.intake import IntakeError
from core.types import IntakeGates
from validation.generator import SyntheticSubmission
from validation.harness import admitted_synthetic

_GATES = IntakeGates(min_ink_pixels=100, min_strokes_whole_drawing=2,
                     max_text_length=200, max_atoms=64)
_CANVAS_PX = 512


def _rectangle(x_min: float, y_min: float, side: float) -> list[list[float]]:
    x_max, y_max = x_min + side, y_min + side
    return [[x_min, y_min], [x_max, y_min], [x_max, y_max],
            [x_min, y_max], [x_min, y_min]]


def _relation_row(key: str, side: float, relation: str = "left-of",
                  ) -> SyntheticSubmission:
    """One row with two labeled rectangles, each with the given side."""
    record = {
        "impressions": ["a tree"],
        "canvas_strokes": [
            {"points": _rectangle(0.1, 0.1, side), "group_id": "g1"},
            {"points": _rectangle(0.6, 0.6, side), "group_id": "g2"}],
        "groups": [{"id": "g1", "label": "a tree"},
                   {"id": "g2", "label": "a wall"}],
        "relations": [{"relation": relation, "of": ["g1", "g2"]}],
        "pasted_text": None,
    }
    return SyntheticSubmission(key=key, record=record, image_id="i" * 64,
                               level=0)


def _text_row(key: str) -> SyntheticSubmission:
    record = {"impressions": ["a tree"], "canvas_strokes": [], "groups": [],
              "relations": [], "pasted_text": None}
    return SyntheticSubmission(key=key, record=record, image_id="i" * 64,
                               level=3)


def test_a_row_below_the_ink_gate_is_refused_and_named() -> None:
    # A side of 0.01 is about 5 pixels on the 512 canvas, thus the two
    # rectangles together are far below 100 line pixels.
    rows = [_relation_row("synthetic://1/000000", 0.2),
            _relation_row("synthetic://1/000001", 0.01),
            _text_row("synthetic://1/000002")]
    kept, refused = admitted_synthetic(rows, _GATES, _CANVAS_PX)
    assert [row.key for row in kept] == ["synthetic://1/000000",
                                         "synthetic://1/000002"]
    assert refused == ["synthetic://1/000001"]


def test_each_admitted_row_is_the_input_row() -> None:
    rows = [_relation_row("synthetic://1/000000", 0.2),
            _text_row("synthetic://1/000001")]
    kept, refused = admitted_synthetic(rows, _GATES, _CANVAS_PX)
    assert kept == rows
    assert refused == []


def test_a_refusal_with_a_different_cause_raises() -> None:
    # The text-length gate is a defect in a generated record, not the
    # small-box condition, thus it stops the run.
    gates = _GATES._replace(max_text_length=3)
    with pytest.raises(IntakeError, match="text-length"):
        admitted_synthetic([_text_row("synthetic://1/000000")], gates,
                           _CANVAS_PX)
