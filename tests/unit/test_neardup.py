"""Unit tests for the s06 near-duplicate decision function."""

import math

import numpy as np
import pytest

from pool.curation.stages.neardup import STAGE, neardup_decisions


def _angle_vector(degrees: float) -> list[float]:
    radians = math.radians(degrees)
    return [math.cos(radians), math.sin(radians)]


def test_cosine_at_threshold_is_rejected() -> None:
    # The float32 cosine of these rows is the float32 value of 0.95.
    vectors = np.array(
        [[1.0, 0.0], [0.95, math.sqrt(1.0 - 0.95**2)]], dtype=np.float32
    )
    result = neardup_decisions(["aa", "bb"], [100, 100], vectors, 0.95)
    assert result.survivors == ("aa",)
    assert len(result.rejections) == 1
    rejection = result.rejections[0]
    assert rejection.key == "bb"
    assert rejection.stage == STAGE
    assert rejection.stage == "s06-neardup"
    assert rejection.reason == "near-duplicate"
    assert rejection.measured == 0.95
    assert rejection.detail == "aa"


def test_cosine_below_threshold_is_kept() -> None:
    vectors = np.array(
        [[1.0, 0.0], [0.9499, math.sqrt(1.0 - 0.9499**2)]], dtype=np.float32
    )
    result = neardup_decisions(["aa", "bb"], [100, 100], vectors, 0.95)
    assert result.survivors == ("aa", "bb")
    assert result.rejections == ()


def test_equal_areas_use_image_id_ascending() -> None:
    vectors = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    result = neardup_decisions(["b", "a"], [100, 100], vectors, 0.95)
    assert result.survivors == ("a",)
    assert result.rejections[0].key == "b"
    assert result.rejections[0].detail == "a"


def test_larger_area_is_kept() -> None:
    vectors = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    result = neardup_decisions(["a", "b"], [100, 400], vectors, 0.95)
    assert result.survivors == ("b",)
    assert result.rejections[0].key == "a"
    assert result.rejections[0].detail == "b"


def test_transitive_chain_is_greedy_not_clustering() -> None:
    # cos(15 deg) is above 0.95, cos(30 deg) is below. The walk keeps
    # "a", rejects "b" against "a", and keeps "c".
    vectors = np.array(
        [_angle_vector(0.0), _angle_vector(15.0), _angle_vector(30.0)],
        dtype=np.float32,
    )
    result = neardup_decisions(["a", "b", "c"], [10, 10, 10], vectors, 0.95)
    assert result.survivors == ("a", "c")
    assert [rejection.key for rejection in result.rejections] == ["b"]
    assert result.rejections[0].detail == "a"


def test_survivors_sorted_by_image_id() -> None:
    vectors = np.eye(3, dtype=np.float32)
    result = neardup_decisions(["z", "m", "a"], [300, 200, 100], vectors, 0.95)
    assert result.survivors == ("a", "m", "z")
    assert result.rejections == ()


def test_accounting_and_rejection_walk_sequence() -> None:
    vectors = np.array(
        [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0]], dtype=np.float32
    )
    result = neardup_decisions(["a", "b", "c", "d"], [10, 10, 10, 10], vectors, 0.95)
    assert len(result.survivors) + len(result.rejections) == 4
    assert result.survivors == ("a", "c")
    assert [rejection.key for rejection in result.rejections] == ["b", "d"]
    for rejection in result.rejections:
        assert rejection.stage == STAGE
        assert rejection.reason == "near-duplicate"
        assert rejection.measured == 1.0
    assert result.rejections[0].detail == "a"
    assert result.rejections[1].detail == "c"


def test_empty_input() -> None:
    vectors = np.zeros((0, 4), dtype=np.float32)
    result = neardup_decisions([], [], vectors, 0.95)
    assert result.survivors == ()
    assert result.rejections == ()


def test_mismatched_lengths_raise() -> None:
    vectors = np.eye(2, dtype=np.float32)
    with pytest.raises(ValueError):
        neardup_decisions(["a", "b"], [10], vectors, 0.95)
