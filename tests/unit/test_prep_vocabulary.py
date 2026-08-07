"""Unit tests for the p04 vocabulary, incidence table, and mean."""

import numpy as np
import pytest

from pool.preparation.stages.vocabulary import (
    vector_mean,
    vocabulary_build,
    vocabulary_frequencies,
    vocabulary_incidence,
)


def test_vocabulary_is_sorted_and_deduplicated() -> None:
    capped = [("tree", "rock"), ("rock", "sky")]
    assert vocabulary_build(capped) == ("rock", "sky", "tree")


def test_frequencies_count_images_one_time_each() -> None:
    capped = [("tree", "rock"), ("rock", "sky")]
    vocabulary = vocabulary_build(capped)
    assert vocabulary_frequencies(vocabulary, capped) == (2, 1, 1)


def test_frequencies_unknown_element_raises() -> None:
    with pytest.raises(ValueError, match="not in the vocabulary"):
        vocabulary_frequencies(("rock",), [("rock", "tree")])


def test_incidence_dtype_shape_and_padding() -> None:
    capped = [("tree", "rock"), ("rock", "sky")]
    vocabulary = vocabulary_build(capped)
    table = vocabulary_incidence(["a", "b"], capped, vocabulary, max_elements=4)
    assert table.dtype == np.int32
    assert table.shape == (2, 4)
    assert table[0].tolist() == [2, 0, -1, -1]
    assert table[1].tolist() == [0, 1, -1, -1]


def test_incidence_rows_decode_back_to_capped_sequences() -> None:
    capped = [("tree", "rock"), ("rock", "sky")]
    vocabulary = vocabulary_build(capped)
    table = vocabulary_incidence(["a", "b"], capped, vocabulary, max_elements=3)
    for row, sequence in zip(table, capped):
        decoded = tuple(vocabulary[index] for index in row if index != -1)
        assert decoded == sequence


def test_incidence_unknown_element_raises() -> None:
    with pytest.raises(ValueError, match="not in the vocabulary"):
        vocabulary_incidence(["a"], [("mystery",)], ("rock",), max_elements=2)


def test_incidence_sequence_longer_than_cap_raises() -> None:
    with pytest.raises(ValueError, match="more than"):
        vocabulary_incidence(["a"], [("rock", "sky")], ("rock", "sky"), max_elements=1)


def test_incidence_misaligned_lengths_raise() -> None:
    with pytest.raises(ValueError, match="does not agree"):
        vocabulary_incidence(["a", "b"], [("rock",)], ("rock",), max_elements=1)


def test_vector_mean_shape_dtype_and_value() -> None:
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    mean = vector_mean(vectors)
    assert mean.dtype == np.float32
    assert mean.shape == (2,)
    assert mean.tolist() == [0.5, 0.5]


def test_vector_mean_is_the_raw_mean_not_unit_norm() -> None:
    vectors = np.array([[0.6, 0.8], [0.6, 0.8]], dtype=np.float32)
    mean = vector_mean(vectors)
    # The stored mean is raw (D11): the norm here is 1, only because
    # the rows agree - a mixed population has norm below 1.
    assert np.allclose(mean, [0.6, 0.8])
    mixed = vector_mean(np.array([[1.0, 0.0], [-1.0, 0.0]], dtype=np.float32))
    assert mixed.tolist() == [0.0, 0.0]


def test_vector_mean_empty_raises() -> None:
    with pytest.raises(ValueError, match="M >= 1"):
        vector_mean(np.zeros((0, 4), dtype=np.float32))
