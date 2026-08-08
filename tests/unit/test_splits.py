"""Unit tests for the D8 hash-based splits."""

import pytest

from pipeline.config import SplitFractionsSection
from validation.splits import (select_keys, selection_key, split_fraction,
                               split_of)

FRACTIONS = SplitFractionsSection(background=0.5, v1=0.25, v2=0.25)
KEYS = [f"pair/{i:05d}" for i in range(200)]


def test_the_sampling_fraction_is_pinned() -> None:
    assert split_fraction("salt", "key") == pytest.approx(
        0.2901372090905109, abs=0.0)


def test_the_splits_partition_the_keys() -> None:
    names = [split_of("s", key, FRACTIONS) for key in KEYS]
    assert set(names) <= {"background", "v1", "v2"}
    counts = {name: names.count(name) for name in set(names)}
    assert sum(counts.values()) == len(KEYS)


def test_fractions_below_one_leave_a_tail() -> None:
    thin = SplitFractionsSection(background=0.01, v1=0.01, v2=0.01)
    names = [split_of("s", key, thin) for key in KEYS]
    assert None in names


def test_the_ranges_are_half_open_at_the_measured_fraction() -> None:
    value = split_fraction("edge-salt", "edge-key")
    at_edge = SplitFractionsSection(background=value, v1=0.2, v2=0.2)
    # The background range is [0, value): the key itself sits in v1.
    assert split_of("edge-salt", "edge-key", at_edge) == "v1"
    above = SplitFractionsSection(background=value + 1e-12, v1=0.2, v2=0.2)
    assert split_of("edge-salt", "edge-key", above) == "background"


def test_selection_ignores_the_enumeration_sequence() -> None:
    shuffled = list(reversed(KEYS))
    forward = select_keys(KEYS, "s", FRACTIONS, "v1", 10)
    backward = select_keys(shuffled, "s", FRACTIONS, "v1", 10)
    assert forward == backward
    assert forward == sorted(forward, key=lambda k: selection_key("s", k))


def test_a_short_split_raises() -> None:
    with pytest.raises(ValueError, match="requested"):
        select_keys(KEYS, "s", FRACTIONS, "v2", len(KEYS))


def test_an_unknown_split_name_raises() -> None:
    with pytest.raises(ValueError, match="unknown split name"):
        select_keys(KEYS, "s", FRACTIONS, "v3", 1)
