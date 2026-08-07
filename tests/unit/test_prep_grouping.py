"""Unit tests for the p08 connected-component grouping."""

import math

import numpy as np
import pytest

from pool.preparation.stages.neardup import neardup_groups
from pool.preparation.types import GroupRow


def _angle_vector(degrees: float) -> list[float]:
    radians = math.radians(degrees)
    return [math.cos(radians), math.sin(radians)]


def test_transitive_chain_is_one_component() -> None:
    # cos(15 deg) is above 0.95, cos(30 deg) is below: a-b and b-c are
    # edges, a-c is not. Connected components make one group of three.
    vectors = np.array(
        [_angle_vector(0.0), _angle_vector(15.0), _angle_vector(30.0)],
        dtype=np.float32,
    )
    rows, histogram = neardup_groups(["a", "b", "c"], vectors, 0.95)
    assert rows == (
        GroupRow(image_id="a", group_id="a", member_count=3),
        GroupRow(image_id="b", group_id="a", member_count=3),
        GroupRow(image_id="c", group_id="a", member_count=3),
    )
    assert histogram == ((3, 1),)


def test_group_id_is_the_smallest_member_id() -> None:
    vectors = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    rows, _ = neardup_groups(["m", "z"], vectors, 0.95)
    assert [row.group_id for row in rows] == ["m", "m"]


def test_singletons_and_histogram() -> None:
    vectors = np.eye(3, dtype=np.float32)
    rows, histogram = neardup_groups(["a", "b", "c"], vectors, 0.95)
    assert rows == (
        GroupRow(image_id="a", group_id="a", member_count=1),
        GroupRow(image_id="b", group_id="b", member_count=1),
        GroupRow(image_id="c", group_id="c", member_count=1),
    )
    assert histogram == ((1, 3),)


def test_mixed_group_counts_histogram_is_sorted() -> None:
    vectors = np.array(
        [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 1.0], [-1.0, 0.0]],
        dtype=np.float32,
    )
    rows, histogram = neardup_groups(["a", "b", "c", "d", "e"], vectors, 0.95)
    assert histogram == ((1, 1), (2, 2))
    assert [row.group_id for row in rows] == ["a", "a", "c", "c", "e"]


def test_cosine_at_the_float32_threshold_is_an_edge() -> None:
    # The float32 cosine of these rows is the float32 value of 0.95,
    # and at-or-above joins the pair.
    vectors = np.array(
        [[1.0, 0.0], [0.95, math.sqrt(1.0 - 0.95**2)]], dtype=np.float32
    )
    rows, histogram = neardup_groups(["a", "b"], vectors, 0.95)
    assert [row.group_id for row in rows] == ["a", "a"]
    assert histogram == ((2, 1),)


def test_cosine_below_the_threshold_is_no_edge() -> None:
    vectors = np.array(
        [[1.0, 0.0], [0.9499, math.sqrt(1.0 - 0.9499**2)]], dtype=np.float32
    )
    rows, _ = neardup_groups(["a", "b"], vectors, 0.95)
    assert [row.group_id for row in rows] == ["a", "b"]


def test_empty_input() -> None:
    rows, histogram = neardup_groups([], np.zeros((0, 4), dtype=np.float32), 0.95)
    assert rows == ()
    assert histogram == ()


def test_unsorted_ids_raise() -> None:
    vectors = np.eye(2, dtype=np.float32)
    with pytest.raises(ValueError, match="strictly ascending"):
        neardup_groups(["b", "a"], vectors, 0.95)


def test_duplicate_ids_raise() -> None:
    vectors = np.eye(2, dtype=np.float32)
    with pytest.raises(ValueError, match="strictly ascending"):
        neardup_groups(["a", "a"], vectors, 0.95)


def test_wrong_dtype_raises() -> None:
    vectors = np.eye(2, dtype=np.float64)
    with pytest.raises(ValueError, match="float32"):
        neardup_groups(["a", "b"], vectors, 0.95)


def test_wrong_shape_raises() -> None:
    vectors = np.zeros((3, 2), dtype=np.float32)
    with pytest.raises(ValueError, match="shape"):
        neardup_groups(["a", "b"], vectors, 0.95)
    with pytest.raises(ValueError, match="shape"):
        neardup_groups(["a", "b"], np.zeros((2, 2, 2), dtype=np.float32), 0.95)
