"""Unit tests for the p03 rarity cap and the D8 equal-value rule."""

import math

import pytest

from core.canonical import quantize_measured
from pool.preparation.stages.cap import cap_decisions


def test_no_cuts_at_or_below_the_cap() -> None:
    sequences = [("e1", "e2"), ("e1",)]
    capped, cuts = cap_decisions(["a", "b"], sequences, 2)
    assert capped == (("e1", "e2"), ("e1",))
    assert cuts == ()


def test_boundary_at_21_with_an_equal_df_pair() -> None:
    # Image "a" has 21 entries e00..e20 in flatten sequence. Two of
    # them are in one other image each: df(e05) == df(e10) == 2, all
    # others df == 1. With max_elements 20 one entry is cut. The
    # equal-df pair breaks by flatten position: e05 (position 5) is
    # kept, e10 (position 10) is cut.
    entries_a = tuple(f"e{index:02d}" for index in range(21))
    sequences = [entries_a, ("e05",), ("e10",)]
    capped, cuts = cap_decisions(["a", "b", "c"], sequences, 20)

    expected_kept = tuple(entry for entry in entries_a if entry != "e10")
    assert capped[0] == expected_kept
    assert len(capped[0]) == 20
    # The other images stay below the cap and keep their sequences.
    assert capped[1] == ("e05",)
    assert capped[2] == ("e10",)

    assert len(cuts) == 1
    cut = cuts[0]
    assert cut.image_id == "a"
    assert cut.element == "e10"
    assert cut.df == 2
    assert cut.capping_rarity == quantize_measured(-math.log(2 / 3))


def test_kept_entries_keep_their_p02_relative_sequence() -> None:
    # The element with df 3 is the only cut. The kept entries stay in
    # the p02 sequence with it removed, not in rarity sequence.
    sequences = [
        ("common", "rare1", "rare2", "rare3"),
        ("common",),
        ("common",),
    ]
    capped, cuts = cap_decisions(["a", "b", "c"], sequences, 3)
    assert capped[0] == ("rare1", "rare2", "rare3")
    assert [cut.element for cut in cuts] == ["common"]
    assert cuts[0].df == 3


def test_cuts_sorted_by_image_id_then_position() -> None:
    # The two images cut the two highest-df entries each. Positions of
    # the cut entries in each sequence are ascending in the output.
    sequences = [
        ("x", "r1", "y", "r2"),
        ("y", "x", "r3", "r4"),
    ]
    capped, cuts = cap_decisions(["a", "b"], sequences, 2)
    assert capped == (("r1", "r2"), ("r3", "r4"))
    assert [(cut.image_id, cut.element) for cut in cuts] == [
        ("a", "x"), ("a", "y"), ("b", "y"), ("b", "x"),
    ]


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError, match="does not agree"):
        cap_decisions(["a", "b"], [("e1",)], 20)


def test_unsorted_ids_raise() -> None:
    with pytest.raises(ValueError, match="strictly ascending"):
        cap_decisions(["b", "a"], [("e1",), ("e2",)], 20)


def test_duplicate_ids_raise() -> None:
    with pytest.raises(ValueError, match="strictly ascending"):
        cap_decisions(["a", "a"], [("e1",), ("e2",)], 20)


def test_max_elements_below_one_raises() -> None:
    with pytest.raises(ValueError, match="max_elements"):
        cap_decisions(["a"], [("e1",)], 0)
