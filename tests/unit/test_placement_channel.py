"""Unit tests for the Layer 4 placement channel (spec P4 section 9)."""

import dataclasses

import numpy as np
import pytest

from core.channels.placement import (atom_boxes, box_area, placement_channel,
                                     soft_check, stroke_bounding_box)
from core.types import Atom, EncodedSubmission, PlacementConfig
from providers.fake.text_encoder import FakeTextEncoder
from tests.conftest import make_pool_index

DIMENSION = 8
CONFIG = PlacementConfig(check_rule="axis-ramp-v1",
                         relation_vocabulary=("left-of", "right-of",
                                              "above", "below"),
                         area_cap=0.9, margin=0.2)

LEFT_BOX = (0.1, 0.4, 0.3, 0.6)
RIGHT_BOX = (0.7, 0.4, 0.9, 0.6)
TOP_BOX = (0.4, 0.05, 0.6, 0.25)
FULL_BOX = (0.01, 0.01, 0.99, 0.99)


def _atom(atom_id: str, text: str | None = None, strokes=None,
          atom_type: str = "DESCRIPTION", refers_to=None,
          relation: str | None = None) -> Atom:
    return Atom(id=atom_id, type=atom_type, subtype=None, text=text,
                strokes=strokes, refers_to=refers_to, relation=relation)


def _encoder() -> FakeTextEncoder:
    return FakeTextEncoder(dimension=DIMENSION)


def _index():
    """Two images with mirrored geometry for "tower" and "boat".

    Image a puts the tower left of the boat, image b the opposite, and
    the two images hold a near-full-frame "sky" above the area cap. The
    vocabulary vectors come from the fake text encoder, thus an atom
    with the element string as its text matches it accurately.
    """
    ids = ("a" * 64, "b" * 64)
    vocabulary = ("boat", "sky", "tower")
    vectors = _encoder().encode_texts(vocabulary).astype(np.float32)
    incidence = np.asarray([[0, 1, 2], [0, 1, 2]], dtype=np.int32)
    table = np.zeros((2, 3, 4), dtype=np.float32)
    mask = np.ones((2, 3), dtype=np.bool_)
    table[0, 2] = LEFT_BOX      # image a: tower left
    table[0, 0] = RIGHT_BOX     # image a: boat right
    table[0, 1] = FULL_BOX      # sky, above the cap
    table[1, 2] = RIGHT_BOX     # image b: tower right
    table[1, 0] = LEFT_BOX      # image b: boat left
    table[1, 1] = FULL_BOX
    return make_pool_index(
        index_id="f" * 64, image_ids=ids,
        outline_vectors=np.zeros((2, 6, DIMENSION), dtype=np.float32),
        outline_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        group_ids=ids,
        pool_image_count=2, vocabulary=vocabulary, pool_frequency=(1, 2, 1),
        vocabulary_vectors=vectors, incidence=incidence,
        element_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        box_table=table, box_mask=mask)


def _submission(*atoms: Atom) -> EncodedSubmission:
    encoder = _encoder()
    texts = [atom for atom in atoms
             if atom.type == "DESCRIPTION" and atom.text is not None]
    vectors = {}
    if texts:
        rows = encoder.encode_texts([atom.text for atom in texts])
        vectors = {atom.id: rows[number]
                   for number, atom in enumerate(texts)}
    return EncodedSubmission(atoms=tuple(atoms), vectors=vectors)


# --- soft_check -----------------------------------------------------------


def test_the_ramp_is_pinned_at_its_three_named_points() -> None:
    at_margin = (0.5 - CONFIG.margin, 0.4, 0.5 + CONFIG.margin, 0.6)
    center = (0.4, 0.4, 0.6, 0.6)
    # Centers level: the check reads 0.5.
    assert soft_check("left-of", center, center, CONFIG.margin) == 0.5
    # B a full margin to the right of A: the check reads 1.
    b_right = (0.4 + CONFIG.margin, 0.4, 0.6 + CONFIG.margin, 0.6)
    assert soft_check("left-of", center, b_right,
                      CONFIG.margin) == pytest.approx(1.0)
    # And a full margin to the left: 0.
    b_left = (0.4 - CONFIG.margin, 0.4, 0.6 - CONFIG.margin, 0.6)
    assert soft_check("left-of", center, b_left,
                      CONFIG.margin) == pytest.approx(0.0)
    assert at_margin  # keeps the fixture where the reader can see it


def test_the_ramp_clamps_past_the_margin() -> None:
    a = (0.0, 0.0, 0.1, 0.1)
    b = (0.9, 0.9, 1.0, 1.0)
    assert soft_check("left-of", a, b, CONFIG.margin) == 1.0
    assert soft_check("right-of", a, b, CONFIG.margin) == 0.0


def test_above_reads_the_canvas_y_axis_down() -> None:
    # The canvas y axis points down (P2 D2): a smaller y is above.
    assert soft_check("above", TOP_BOX, LEFT_BOX, CONFIG.margin) == 1.0
    assert soft_check("below", TOP_BOX, LEFT_BOX, CONFIG.margin) == 0.0


def test_an_unknown_relation_raises_in_the_check() -> None:
    with pytest.raises(ValueError, match="unknown relation"):
        soft_check("inside", LEFT_BOX, RIGHT_BOX, CONFIG.margin)


def test_stroke_bounding_box_and_area() -> None:
    strokes = (((0.1, 0.2), (0.5, 0.4)), ((0.3, 0.1),))
    assert stroke_bounding_box(strokes) == (0.1, 0.1, 0.5, 0.4)
    assert box_area((0.0, 0.0, 0.5, 0.4)) == pytest.approx(0.2)


# --- locating -------------------------------------------------------------


def test_a_text_atom_locates_through_the_image() -> None:
    index = _index()
    tower = _atom("a1", text="tower")
    boxes_a = atom_boxes(_submission(tower), index, 0, CONFIG)
    boxes_b = atom_boxes(_submission(tower), index, 1, CONFIG)
    assert boxes_a["a1"] == pytest.approx(LEFT_BOX)
    assert boxes_b["a1"] == pytest.approx(RIGHT_BOX)


def test_a_near_full_frame_box_does_not_locate() -> None:
    index = _index()
    sky = _atom("a1", text="sky")
    assert atom_boxes(_submission(sky), index, 0, CONFIG) == {}


def test_a_strokes_only_atom_locates_by_its_canvas_box() -> None:
    index = _index()
    # No text, thus no Layer 2 vector: the canvas box is the one
    # rule, and it gives the same box in each image (Rule 2).
    group = _atom("a1", strokes=(((0.2, 0.2), (0.4, 0.4)),))
    for position in (0, 1):
        boxes = atom_boxes(_submission(group), index, position, CONFIG)
        assert boxes["a1"] == pytest.approx((0.2, 0.2, 0.4, 0.4))


def test_a_text_atom_with_no_usable_box_does_not_locate() -> None:
    index = _index()
    # The capped "sky" slot gives the atom no box, and its strokes
    # must not step in: an image with no detector data must not score
    # as agreement (review ruling 2026-08-10).
    group = _atom("a1", text="sky",
                  strokes=(((0.2, 0.2), (0.4, 0.4)),))
    assert atom_boxes(_submission(group), index, 0, CONFIG) == {}


# --- the channel ----------------------------------------------------------


def _relation_submission(relation: str) -> EncodedSubmission:
    tower = _atom("a1", text="tower")
    boat = _atom("a2", text="boat")
    stated = _atom("a3", atom_type="RELATION", refers_to=("a1", "a2"),
                   relation=relation)
    return _submission(tower, boat, stated)


def test_the_channel_discriminates_by_image_geometry() -> None:
    index = _index()
    scores = placement_channel(_relation_submission("left-of"), index,
                               CONFIG)
    assert scores.shape == (2,)
    assert scores.dtype == np.float32
    # Image a puts the tower left of the boat, image b the opposite.
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0)
    mirrored = placement_channel(_relation_submission("right-of"), index,
                                 CONFIG)
    assert mirrored[0] == pytest.approx(0.0)
    assert mirrored[1] == pytest.approx(1.0)


def test_a_relation_outside_the_vocabulary_contributes_nothing() -> None:
    index = _index()
    narrow = CONFIG._replace(relation_vocabulary=("above", "below"))
    scores = placement_channel(_relation_submission("left-of"), index,
                               narrow)
    assert scores[0] == 0.0 and scores[1] == 0.0


def test_a_relation_that_does_not_fire_adds_zero() -> None:
    index = _index()
    tower = _atom("a1", text="tower")
    boat = _atom("a2", text="boat")
    good = _atom("a3", atom_type="RELATION", refers_to=("a1", "a2"),
                 relation="left-of")
    sky = _atom("a4", text="sky")
    unlocated = _atom("a5", atom_type="RELATION", refers_to=("a1", "a4"),
                      relation="left-of")
    scores = placement_channel(_submission(tower, boat, sky, good,
                                           unlocated), index, CONFIG)
    # The firing relation scores 1.0 and the unlocated one adds
    # zero — the score is the sum, with no stated-count denominator
    # (ruling 2026-08-10).
    assert scores[0] == pytest.approx(1.0)


def test_an_image_with_a_masked_box_scores_zero() -> None:
    index = _index()
    masked = index.box_mask.copy()
    masked[1, :] = False
    no_boxes = dataclasses.replace(index, box_mask=masked)
    scores = placement_channel(_relation_submission("left-of"), no_boxes,
                               CONFIG)
    # Image a fires at 1.0 as before. Image b holds no usable box,
    # thus nothing locates there and nothing fires — missing
    # detector data must not score as agreement.
    assert scores[0] == pytest.approx(1.0)
    assert scores[1] == pytest.approx(0.0)


def test_a_submission_with_no_relation_raises() -> None:
    index = _index()
    with pytest.raises(ValueError, match="needs one RELATION atom"):
        placement_channel(_submission(_atom("a1", text="tower")), index,
                          CONFIG)


def test_config_validation_raises_on_unknown_rules() -> None:
    index = _index()
    with pytest.raises(ValueError, match="unknown check_rule"):
        placement_channel(_relation_submission("left-of"), index,
                          CONFIG._replace(check_rule="hard-boolean"))
    with pytest.raises(ValueError, match="unknown relations"):
        placement_channel(_relation_submission("left-of"), index,
                          CONFIG._replace(relation_vocabulary=("inside",)))
