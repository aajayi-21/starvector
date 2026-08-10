"""Unit tests for the Layer 4 outline channel on hand-built vectors."""

import numpy as np
import pytest

from core.channels.outline import outline_channel, outline_scores
from core.types import Atom, EncodedSubmission, OutlineConfig, PoolIndex
from tests.conftest import make_pool_index

CONFIG = OutlineConfig(comparison_rule="center-cosine-v1")
DIMENSION = 4


def _unit(vector: list[float]) -> np.ndarray:
    array = np.asarray(vector, dtype=np.float32)
    return array / np.linalg.norm(array)


def _index(rows_by_image: list[list[list[float]]],
           mean: list[float] | None = None) -> PoolIndex:
    count = len(rows_by_image)
    stacked = np.asarray(rows_by_image, dtype=np.float32)   # (N, 6, d)
    image_ids = tuple(f"{chr(97 + i)}" * 64 for i in range(count))
    return make_pool_index(
        index_id="f" * 64,
        image_ids=image_ids,
        outline_vectors=stacked,
        outline_space_mean=np.asarray(
            mean if mean is not None else [0.0] * DIMENSION,
            dtype=np.float32),
        group_ids=image_ids,
    )


def test_the_best_row_wins_and_the_output_is_pinned() -> None:
    e0 = [1.0, 0.0, 0.0, 0.0]
    e1 = [0.0, 1.0, 0.0, 0.0]
    minus_e0 = [-1.0, 0.0, 0.0, 0.0]
    index = _index([
        [e1, e1, e1, e0, e1, e1],   # one row agrees fully
        [e1] * 6,                   # orthogonal on each row
        [minus_e0] * 6,             # opposite on each row
    ])
    scores = outline_scores(_unit(e0), index, CONFIG)
    assert scores.shape == (3,)
    assert scores.dtype == np.float32
    assert scores == pytest.approx([1.0, 0.0, -1.0])


def test_mean_subtraction_changes_the_score() -> None:
    # Raw cosine between sketch e0+e1 and pool row 2*e1 is positive.
    # After centering on mean e1 the sketch is e0 and the row is e1 —
    # the score drops to zero.
    sketch = np.asarray([1.0, 1.0, 0.0, 0.0], dtype=np.float32)
    index = _index([[[0.0, 2.0, 0.0, 0.0]] * 6],
                   mean=[0.0, 1.0, 0.0, 0.0])
    scores = outline_scores(sketch, index, CONFIG)
    assert scores == pytest.approx([0.0], abs=1e-6)


def test_unknown_comparison_rule_raises() -> None:
    index = _index([[[1.0, 0.0, 0.0, 0.0]] * 6])
    with pytest.raises(ValueError, match="comparison_rule"):
        outline_scores(_unit([1.0, 0.0, 0.0, 0.0]), index,
                       OutlineConfig(comparison_rule="other"))


def test_wrong_sketch_shape_raises() -> None:
    index = _index([[[1.0, 0.0, 0.0, 0.0]] * 6])
    with pytest.raises(ValueError, match="sketch_vector"):
        outline_scores(np.zeros(3, dtype=np.float32), index, CONFIG)


def test_zero_norm_after_centering_raises() -> None:
    mean = [0.0, 1.0, 0.0, 0.0]
    index = _index([[[0.0, 1.0, 0.0, 0.0]] * 6], mean=mean)
    with pytest.raises(ValueError, match="zero vector norm"):
        outline_scores(np.asarray(mean, dtype=np.float32), index, CONFIG)


def _drawing_atom(atom_id: str) -> Atom:
    return Atom(id=atom_id, type="WHOLE-DRAWING", subtype=None, text=None,
                strokes=(((0.0, 0.0), (1.0, 1.0)),), refers_to=None,
                relation=None)


def test_channel_needs_exactly_one_encoded_drawing_atom() -> None:
    index = _index([[[1.0, 0.0, 0.0, 0.0]] * 6])
    vector = _unit([1.0, 0.0, 0.0, 0.0])
    one = EncodedSubmission(atoms=(_drawing_atom("a1"),),
                            vectors={"a1": vector})
    assert outline_channel(one, index, CONFIG).shape == (1,)
    none = EncodedSubmission(atoms=(), vectors={})
    with pytest.raises(ValueError, match="one encoded WHOLE-DRAWING"):
        outline_channel(none, index, CONFIG)
    two = EncodedSubmission(
        atoms=(_drawing_atom("a1"), _drawing_atom("a2")),
        vectors={"a1": vector, "a2": vector})
    with pytest.raises(ValueError, match="one encoded WHOLE-DRAWING"):
        outline_channel(two, index, CONFIG)


def test_a_non_finite_sketch_vector_raises() -> None:
    index = _index([[[1.0, 0.0, 0.0, 0.0]] * 6])
    poisoned = np.asarray([1.0, float("nan"), 0.0, 0.0], dtype=np.float32)
    with pytest.raises(ValueError, match="non-finite"):
        outline_scores(poisoned, index, CONFIG)
