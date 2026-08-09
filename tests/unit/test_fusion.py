"""Unit tests for the Layer 6 formula and the active-set rule."""

import numpy as np
import pytest

from core.fusion import NoActiveChannels, active_channels, fuse
from core.types import ROUTING_TABLE, Atom


def _atom(atom_type: str, atom_id: str = "a1") -> Atom:
    return Atom(id=atom_id, type=atom_type, subtype=None, text=None,
                strokes=None, refers_to=None, relation=None)


def test_the_active_set_comes_from_the_routing_table() -> None:
    assert active_channels([_atom("WHOLE-DRAWING")], ROUTING_TABLE) \
        == frozenset({"outline"})
    assert active_channels([_atom("DESCRIPTION")], ROUTING_TABLE) \
        == frozenset()
    assert active_channels(
        [_atom("DESCRIPTION", "a1"), _atom("WHOLE-DRAWING", "a2"),
         _atom("RELATION", "a3")],
        ROUTING_TABLE) == frozenset({"outline"})
    assert active_channels([], ROUTING_TABLE) == frozenset()


def test_the_formula_is_pinned_on_hand_tables() -> None:
    scores = {
        "a": np.asarray([1.0, 0.0], dtype=np.float32),
        "b": np.asarray([0.0, 1.0], dtype=np.float32),
    }
    fused = fuse(scores, {"a": 1.0, "b": 3.0})
    assert fused == pytest.approx([0.25, 0.75])
    assert fused.dtype == np.float32


def test_the_denominator_renormalizes_across_each_subset() -> None:
    rng = np.random.default_rng(3)
    weights = {"a": 0.7, "b": 0.2, "c": 1.4}
    tables = {name: rng.normal(0.0, 1.0, 8).astype(np.float32)
              for name in weights}
    subsets = [("a",), ("b",), ("c",), ("a", "b"), ("a", "c"),
               ("b", "c"), ("a", "b", "c")]
    for subset in subsets:
        scores = {name: tables[name] for name in subset}
        fused = fuse(scores, weights)
        denominator = sum(weights[name] for name in subset)
        manual = sum(weights[name] * tables[name].astype(np.float64)
                     for name in sorted(subset)) / denominator
        assert fused == pytest.approx(manual, rel=1e-6)


def test_one_channel_makes_the_weight_value_cosmetic() -> None:
    table = np.asarray([0.5, -1.0, 2.0], dtype=np.float32)
    small = fuse({"outline": table}, {"outline": 0.1})
    large = fuse({"outline": table}, {"outline": 10.0})
    assert small == pytest.approx(large)
    assert small == pytest.approx(table)


def test_an_empty_active_set_raises_no_active_channels() -> None:
    with pytest.raises(NoActiveChannels):
        fuse({}, {"outline": 1.0})


def test_a_channel_without_a_weight_raises() -> None:
    with pytest.raises(ValueError, match="no configured weight"):
        fuse({"outline": np.zeros(2, dtype=np.float32)}, {"element": 1.0})


def test_a_length_mismatch_raises() -> None:
    scores = {
        "a": np.zeros(2, dtype=np.float32),
        "b": np.zeros(3, dtype=np.float32),
    }
    with pytest.raises(ValueError, match="length"):
        fuse(scores, {"a": 1.0, "b": 1.0})
