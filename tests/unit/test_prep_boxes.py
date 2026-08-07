"""Unit tests for the p07 box validation limits."""

import pytest

from pool.preparation.stages.boxes import boxes_validate
from pool.preparation.types import Box


def test_valid_response_passes() -> None:
    boxes_validate(
        "img", ["tree", "rock"],
        {"tree": Box(0.1, 0.2, 0.5, 0.9), "rock": Box(0.0, 0.0, 1.0, 1.0)},
    )


def test_none_is_a_permitted_answer() -> None:
    boxes_validate("img", ["tree"], {"tree": None})


def test_empty_query_with_empty_response_is_complete() -> None:
    boxes_validate("img", [], {})


def test_out_of_range_value_raises() -> None:
    with pytest.raises(ValueError, match=r"img.*not in \[0, 1\]"):
        boxes_validate("img", ["tree"], {"tree": Box(0.1, 0.2, 1.2, 0.9)})


def test_negative_value_raises() -> None:
    with pytest.raises(ValueError, match=r"not in \[0, 1\]"):
        boxes_validate("img", ["tree"], {"tree": Box(-0.1, 0.2, 0.5, 0.9)})


def test_inverted_x_raises() -> None:
    with pytest.raises(ValueError, match="minimum is not below maximum"):
        boxes_validate("img", ["tree"], {"tree": Box(0.6, 0.2, 0.5, 0.9)})


def test_degenerate_y_raises() -> None:
    with pytest.raises(ValueError, match="minimum is not below maximum"):
        boxes_validate("img", ["tree"], {"tree": Box(0.1, 0.5, 0.4, 0.5)})


def test_missing_key_raises() -> None:
    with pytest.raises(ValueError, match=r"missing \['rock'\]"):
        boxes_validate("img", ["tree", "rock"], {"tree": None})


def test_extra_key_raises() -> None:
    with pytest.raises(ValueError, match=r"extra \['sky'\]"):
        boxes_validate("img", ["tree"], {"tree": None, "sky": None})
