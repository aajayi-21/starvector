"""Unit tests for the s07 diversity decision functions."""

import math

import numpy as np
import pytest

from pool.curation.stages.diversity import (
    STAGE,
    cluster_count,
    diversity_decisions,
    seeded_kmeans,
)


def _random_unit_vectors(count: int, dimension: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    matrix = rng.normal(size=(count, dimension))
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix.astype(np.float32)


def _ids(count: int) -> list[str]:
    return [f"id{index:04d}" for index in range(count)]


def test_seeded_kmeans_same_seed_gives_identical_labels() -> None:
    vectors = _random_unit_vectors(40, 8, seed=123)
    labels_one = seeded_kmeans(vectors, k=4, seed=7, max_iterations=50)
    labels_two = seeded_kmeans(vectors, k=4, seed=7, max_iterations=50)
    assert labels_one.tobytes() == labels_two.tobytes()
    assert labels_one.dtype == np.int64
    assert labels_one.shape == (40,)
    assert set(np.unique(labels_one)) <= set(range(4))


def test_cluster_count_formula() -> None:
    assert cluster_count(49, 50) == 1
    assert cluster_count(50, 50) == 1
    assert cluster_count(51, 50) == 2
    assert cluster_count(1, 50) == 1
    assert cluster_count(3, 1) == 3


def test_single_cluster_when_count_at_or_below_divisor() -> None:
    vectors = _random_unit_vectors(49, 8, seed=5)
    result = diversity_decisions(
        _ids(49),
        vectors,
        cluster_seed=3,
        cluster_size_divisor=50,
        cluster_cap=10,
        kmeans_max_iterations=50,
    )
    assert len(result.survivors) == 10
    assert len(result.rejections) == 39
    assert {rejection.detail for rejection in result.rejections} == {"cluster-0"}


def test_two_clusters_when_count_above_divisor() -> None:
    vectors = _random_unit_vectors(51, 8, seed=6)
    result = diversity_decisions(
        _ids(51),
        vectors,
        cluster_seed=3,
        cluster_size_divisor=50,
        cluster_cap=10,
        kmeans_max_iterations=50,
    )
    details = {rejection.detail for rejection in result.rejections}
    assert details <= {"cluster-0", "cluster-1"}
    assert len(result.survivors) + len(result.rejections) == 51
    assert len(result.survivors) <= 20
    assert result.survivors == tuple(sorted(result.survivors))


def test_cluster_at_cap_has_zero_rejections() -> None:
    vectors = _random_unit_vectors(5, 4, seed=9)
    result = diversity_decisions(
        _ids(5),
        vectors,
        cluster_seed=1,
        cluster_size_divisor=50,
        cluster_cap=5,
        kmeans_max_iterations=20,
    )
    assert result.survivors == tuple(_ids(5))
    assert result.rejections == ()


def test_cap_plus_one_has_one_rejection_with_cluster_detail() -> None:
    vectors = _random_unit_vectors(6, 4, seed=11)
    result = diversity_decisions(
        _ids(6),
        vectors,
        cluster_seed=1,
        cluster_size_divisor=50,
        cluster_cap=5,
        kmeans_max_iterations=20,
    )
    assert len(result.survivors) == 5
    assert len(result.rejections) == 1
    rejection = result.rejections[0]
    assert rejection.stage == STAGE
    assert rejection.stage == "s07-diversity"
    assert rejection.reason == "diversity-cap"
    assert rejection.measured is None
    assert rejection.detail == "cluster-0"


def test_farthest_point_matches_manual_computation() -> None:
    # Angles 0, 10, 20, and 90 degrees on the unit circle. The medoid
    # is the 20 degree point ("c", greatest summed similarity). The
    # traversal then adds "d" (90 degrees, distance 0.658) and "a"
    # (0 degrees, distance 0.060). "b" (10 degrees) is the rejection.
    angles = [0.0, 10.0, 20.0, 90.0]
    vectors = np.array(
        [[math.cos(math.radians(a)), math.sin(math.radians(a))] for a in angles],
        dtype=np.float32,
    )
    result = diversity_decisions(
        ["a", "b", "c", "d"],
        vectors,
        cluster_seed=0,
        cluster_size_divisor=50,
        cluster_cap=3,
        kmeans_max_iterations=10,
    )
    assert result.survivors == ("a", "c", "d")
    assert [rejection.key for rejection in result.rejections] == ["b"]
    assert result.rejections[0].detail == "cluster-0"


def test_decisions_deterministic_across_two_calls() -> None:
    vectors = _random_unit_vectors(60, 8, seed=21)
    ids = _ids(60)
    result_one = diversity_decisions(
        ids,
        vectors,
        cluster_seed=13,
        cluster_size_divisor=20,
        cluster_cap=4,
        kmeans_max_iterations=50,
    )
    result_two = diversity_decisions(
        ids,
        vectors,
        cluster_seed=13,
        cluster_size_divisor=20,
        cluster_cap=4,
        kmeans_max_iterations=50,
    )
    assert result_one == result_two
    assert len(result_one.survivors) + len(result_one.rejections) == 60


def test_unsorted_image_ids_raise() -> None:
    vectors = _random_unit_vectors(2, 4, seed=1)
    with pytest.raises(ValueError):
        diversity_decisions(
            ["b", "a"],
            vectors,
            cluster_seed=1,
            cluster_size_divisor=50,
            cluster_cap=5,
            kmeans_max_iterations=10,
        )
