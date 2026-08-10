"""Unit tests for the p04 element side of the pool index (P3 section 7).

The context loader accepts only artifacts that agree with each other.
A silently accepted broken table makes plausible numbers that are
incorrect, which is the outcome this system treats as worst.
"""

import numpy as np
import pytest

from pipeline.context import ContextError, ElementSide, build_pool_index
from pool.preparation.types import GroupRow

DIMENSION = 3
IDS = ("a" * 64, "b" * 64)
GROUPS = tuple(GroupRow(image_id=image_id, group_id=image_id, member_count=1)
               for image_id in IDS)


def _side(**overrides) -> ElementSide:
    vectors = np.eye(3, DIMENSION, dtype=np.float32)
    defaults = {
        "vocabulary": ("cliff", "sea", "sky"),
        "pool_frequency": (1, 2, 2),
        "pool_image_count": 2,
        "vocabulary_vectors": vectors,
        "incidence": np.asarray([[0, 1], [1, 2]], dtype=np.int32),
        "element_space_mean": np.zeros(DIMENSION, dtype=np.float32),
    }
    defaults.update(overrides)
    width = defaults["incidence"].shape[1]
    defaults.setdefault(
        "box_table", np.zeros((2, width, 4), dtype=np.float32))
    defaults.setdefault("box_mask", np.zeros((2, width), dtype=np.bool_))
    return ElementSide(**defaults)


def _build(side: ElementSide):
    return build_pool_index(
        index_id="f" * 64, image_ids=IDS,
        outline_vectors=np.zeros((2, 6, DIMENSION), dtype=np.float32),
        outline_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        group_rows=GROUPS, elements=side)


def test_a_clean_element_side_builds() -> None:
    index = _build(_side())
    assert index.vocabulary == ("cliff", "sea", "sky")
    assert index.pool_image_count == 2
    assert index.incidence.shape == (2, 2)


def test_a_bank_shorter_than_the_vocabulary_raises() -> None:
    with pytest.raises(ContextError, match="fewer than"):
        _build(_side(pool_frequency=(1, 2, 2, 1)))


def test_a_bank_longer_than_the_vocabulary_is_permitted() -> None:
    # The V1 union appends photograph elements above the pool entries.
    side = _side(vocabulary=("cliff", "sea", "sky"), pool_frequency=(1, 2))
    assert _build(side).pool_frequency == (1, 2)


def test_a_repeated_entry_string_raises() -> None:
    with pytest.raises(ContextError, match="repeats an entry"):
        _build(_side(vocabulary=("cliff", "cliff", "sky")))


def test_a_frequency_above_the_image_count_raises() -> None:
    with pytest.raises(ContextError, match=r"\[1, pool_image_count\]"):
        _build(_side(pool_frequency=(1, 2, 9)))


def test_a_frequency_below_one_raises() -> None:
    with pytest.raises(ContextError, match=r"\[1, pool_image_count\]"):
        _build(_side(pool_frequency=(0, 2, 2)))


def test_vectors_that_are_not_unit_norm_raise() -> None:
    vectors = np.eye(3, DIMENSION, dtype=np.float32) * 2.0
    with pytest.raises(ContextError, match="unit-norm"):
        _build(_side(vocabulary_vectors=vectors))


def test_a_mean_of_the_wrong_dimension_raises() -> None:
    with pytest.raises(ContextError, match="element_space_mean"):
        _build(_side(element_space_mean=np.zeros(2, dtype=np.float32)))


def test_an_incidence_entry_out_of_range_raises() -> None:
    with pytest.raises(ContextError, match=r"\[-1, 3\)"):
        _build(_side(incidence=np.asarray([[0, 1], [1, 7]], dtype=np.int32)))


def test_an_incidence_of_the_wrong_dtype_raises() -> None:
    with pytest.raises(ContextError, match="int32"):
        _build(_side(incidence=np.asarray([[0, 1], [1, 2]], dtype=np.int64)))


def test_an_image_with_no_element_raises() -> None:
    with pytest.raises(ContextError, match="no element"):
        _build(_side(incidence=np.asarray([[0, 1], [-1, -1]],
                                          dtype=np.int32)))


def test_padding_before_the_last_entry_raises() -> None:
    with pytest.raises(ContextError, match="pads before"):
        _build(_side(incidence=np.asarray([[0, 1], [-1, 2]],
                                          dtype=np.int32)))


def test_a_row_that_names_an_entry_twice_raises() -> None:
    # A column that comes again lets one element accept two units of
    # matched mass. The Sinkhorn marginals give each element one.
    with pytest.raises(ContextError, match="names an entry twice"):
        _build(_side(incidence=np.asarray([[0, 0], [1, 2]], dtype=np.int32)))
