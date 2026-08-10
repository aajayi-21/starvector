"""Unit tests for the Layer 4 element channel on hand-built tables.

Spec: docs/specs/element-channel.md section 15. The rarity shape, the
type rule, the soft matching against a by-hand computation, the tier-1
lookup, stitching, and the flooding property of architecture section
12.1.
"""

import math

import numpy as np
import pytest

from core.channels.element import (element_atoms, element_channel,
                                   image_elements, match_report,
                                   matched_score, rarity_weights,
                                   similarity_table, sinkhorn_plan,
                                   soft_match, tier1_scores)
from core.types import Atom, ElementConfig, EncodedSubmission
from tests.conftest import make_pool_index

DIMENSION = 4
CONFIG = ElementConfig(comparison_rule="element-center-cosine-v1",
                       matching_rule="sinkhorn-slack-v1", epsilon=0.1,
                       sinkhorn_iterations=20, tier2_count=500, alpha=1.0)

# Four orthogonal element vectors: "lighthouse", "cliff", "sea", "sky".
BANK = np.eye(4, DIMENSION, dtype=np.float32)
VOCABULARY = ("lighthouse", "cliff", "sea", "sky")
# "sea" and "sky" are in each image, "lighthouse" in one alone.
FREQUENCY = (1, 2, 3, 3)
IMAGE_COUNT = 3
IDS = tuple(chr(97 + position) * 64 for position in range(IMAGE_COUNT))

# image a: lighthouse, sea, sky.  image b: cliff, sea, sky.
# image c: sea, sky.
INCIDENCE = np.asarray([[0, 2, 3], [1, 2, 3], [2, 3, -1]], dtype=np.int32)


def _atom(atom_id: str, text: str) -> Atom:
    return Atom(id=atom_id, type="DESCRIPTION", subtype=None, text=text,
                strokes=None, refers_to=None, relation=None)


def _submission(*named: tuple[str, np.ndarray]) -> EncodedSubmission:
    atoms = tuple(_atom(f"a{number + 1}", text)
                  for number, (text, _) in enumerate(named))
    vectors = {atom.id: vector.astype(np.float32)
               for atom, (_, vector) in zip(atoms, named)}
    return EncodedSubmission(atoms=atoms, vectors=vectors)


def _index(incidence: np.ndarray = INCIDENCE):
    return make_pool_index(
        index_id="f" * 64, image_ids=IDS,
        outline_vectors=np.zeros((IMAGE_COUNT, 6, DIMENSION),
                                 dtype=np.float32),
        outline_space_mean=np.zeros(DIMENSION, dtype=np.float32),
        group_ids=IDS,
        pool_image_count=IMAGE_COUNT, vocabulary=VOCABULARY,
        pool_frequency=FREQUENCY, vocabulary_vectors=BANK,
        incidence=incidence,
        element_space_mean=np.zeros(DIMENSION, dtype=np.float32))


# --- rarity ---------------------------------------------------------------


def test_the_rarity_shape_agrees_with_the_worked_example() -> None:
    # Architecture section 27: a frequency of 0.09 gives 2.4 nats.
    frequency = (9,)
    similarity = np.ones((1, 1), dtype=np.float32)
    weights = rarity_weights(similarity, frequency, 100)
    assert weights[0] == pytest.approx(2.4, abs=0.01)


def test_rarity_reads_the_best_matching_entry() -> None:
    similarity = similarity_table(BANK, BANK, np.zeros(DIMENSION,
                                                       dtype=np.float32))
    weights = rarity_weights(similarity, FREQUENCY, IMAGE_COUNT)
    assert weights == pytest.approx([
        -math.log(1 / 3), -math.log(2 / 3), 0.0, 0.0])


def test_an_element_in_every_image_gets_weight_zero() -> None:
    similarity = np.asarray([[0.1, 0.9]], dtype=np.float32)
    assert rarity_weights(similarity, (1, 4), 4)[0] == pytest.approx(0.0)


def test_equal_similarity_resolves_to_the_lowest_index() -> None:
    similarity = np.asarray([[0.5, 0.5]], dtype=np.float32)
    # Entry 0 has frequency 1 and entry 1 has frequency 4. The written
    # rule for equal values reads entry 0, thus the weight is larger.
    assert rarity_weights(similarity, (1, 4), 4)[0] == pytest.approx(
        -math.log(1 / 4))


def test_a_frequency_table_of_the_wrong_width_raises() -> None:
    with pytest.raises(ValueError, match="columns"):
        rarity_weights(np.ones((1, 3), dtype=np.float32), (1, 2), 4)


# --- the similarity table -------------------------------------------------


def test_the_similarity_table_centers_the_two_sides() -> None:
    mean = np.asarray([0.5, 0.0, 0.0, 0.0], dtype=np.float32)
    plain = similarity_table(BANK[:1], BANK, np.zeros(DIMENSION,
                                                      dtype=np.float32))
    centered = similarity_table(BANK[:1], BANK, mean)
    assert plain[0, 0] == pytest.approx(1.0)
    assert centered[0, 0] == pytest.approx(1.0)
    # Centering moves the off-diagonal values: the mean subtraction is
    # not cosmetic (architecture section 10).
    assert centered[0, 1] != pytest.approx(plain[0, 1])


def test_a_vector_equal_to_the_mean_raises() -> None:
    mean = BANK[0].copy()
    with pytest.raises(ValueError, match="zero vector norm"):
        similarity_table(BANK[:1], BANK, mean)


def test_an_atom_of_the_wrong_dimension_raises() -> None:
    with pytest.raises(ValueError, match="atom_vectors must have shape"):
        similarity_table(np.ones((1, 3), dtype=np.float32), BANK,
                         np.zeros(DIMENSION, dtype=np.float32))


def test_the_channel_reads_description_atoms_with_text() -> None:
    vector = np.zeros(DIMENSION, dtype=np.float32)
    described = _atom("a1", "a lighthouse")
    unlabeled = Atom(id="a2", type="DESCRIPTION", subtype=None, text=None,
                     strokes=(((0.0, 0.0),),), refers_to=None, relation=None)
    drawing = Atom(id="a3", type="WHOLE-DRAWING", subtype=None, text=None,
                   strokes=(((0.0, 0.0),),), refers_to=None, relation=None)
    relation = Atom(id="a4", type="RELATION", subtype=None, text="left of",
                    strokes=None, refers_to=("a1", "a2"), relation="left of")
    submission = EncodedSubmission(
        atoms=(described, unlabeled, drawing, relation),
        vectors={"a1": vector, "a3": vector, "a4": vector})
    assert element_atoms(submission) == (described,)


# --- soft matching --------------------------------------------------------


def test_the_one_by_one_limit_agrees_with_the_by_hand_value() -> None:
    # With one atom and one element the augmented table is 2 x 2 with
    # marginals of one everywhere. The doubly stochastic scaling of
    # [[exp(c/e), 1], [1, 1]] is [[t, 1-t], [1-t, t]] with
    # t / (1 - t) = sqrt(exp(c/e)), thus t = s / (1 + s) at
    # s = exp(c / (2e)). The iteration reaches that limit. The pinned
    # count of twenty stops short of it on purpose (D3).
    similarity = np.asarray([[1.0]], dtype=np.float32)
    converged = sinkhorn_plan(similarity,
                              CONFIG._replace(sinkhorn_iterations=4000))
    s = math.exp(1.0 / (2 * CONFIG.epsilon))
    assert converged[0, 0] == pytest.approx(s / (1 + s), abs=1e-9)
    assert converged.shape == (2, 2)


def test_the_pinned_count_stops_short_of_the_limit() -> None:
    # A recorded property, not a target: at epsilon 0.10 twenty
    # alternations do not converge. The plan stays deterministic and
    # keeps the atom marginal accurate, which is what the score uses.
    similarity = np.asarray([[1.0]], dtype=np.float32)
    pinned = sinkhorn_plan(similarity, CONFIG)[0, 0]
    s = math.exp(1.0 / (2 * CONFIG.epsilon))
    assert 0.9 < pinned < s / (1 + s)


def test_the_atom_marginal_is_exact_and_the_others_are_close() -> None:
    rng = np.random.default_rng(5)
    similarity = rng.uniform(-1.0, 1.0, (4, 6)).astype(np.float32)
    plan = sinkhorn_plan(similarity, CONFIG)
    # The sequence ends on a row rescaling, thus each atom holds one
    # unit accurately and the reserve row k units accurately.
    assert plan.sum(axis=1) == pytest.approx([1.0, 1.0, 1.0, 1.0, 6.0],
                                             abs=1e-12)
    # The column totals are approached, not reached, at the pinned
    # count: one element absorbs about one unit.
    assert plan.sum(axis=0) == pytest.approx([1.0] * 6 + [4.0], abs=0.2)


def test_no_atom_holds_more_than_one_unit_of_mass() -> None:
    # The bound the score relies on: an atom cannot contribute more
    # than its rarity weight times its best similarity.
    rng = np.random.default_rng(9)
    for count in (1, 2, 5):
        similarity = rng.uniform(-1.0, 1.0, (count, 3)).astype(np.float32)
        plan = soft_match(similarity, CONFIG)
        assert bool((plan.sum(axis=1) <= 1.0 + 1e-12).all())


def test_unmatched_mass_parks_on_the_reserve() -> None:
    # One atom that matches nothing: its mass goes to the reserve
    # column, not to a pairing it does not have.
    similarity = np.asarray([[1.0, -1.0], [-1.0, -1.0]], dtype=np.float32)
    plan = sinkhorn_plan(similarity, CONFIG)
    assert plan[0, 0] > 0.9
    assert plan[1, 2] > 0.9


def test_the_plan_is_deterministic_byte_for_byte() -> None:
    rng = np.random.default_rng(11)
    similarity = rng.uniform(-1.0, 1.0, (3, 5)).astype(np.float32)
    first = sinkhorn_plan(similarity, CONFIG)
    second = sinkhorn_plan(similarity, CONFIG)
    assert first.tobytes() == second.tobytes()
    assert first.dtype == np.float64


def test_the_matched_region_drops_the_reserve_bins() -> None:
    similarity = np.asarray([[0.5, 0.2]], dtype=np.float32)
    assert soft_match(similarity, CONFIG).shape == (1, 2)


def test_a_non_finite_similarity_raises() -> None:
    similarity = np.asarray([[np.nan]], dtype=np.float32)
    with pytest.raises(ValueError, match="non-finite"):
        sinkhorn_plan(similarity, CONFIG)


def test_the_score_weights_each_pairing_by_rarity() -> None:
    similarity = np.asarray([[1.0, 0.0]], dtype=np.float32)
    plan = np.asarray([[0.5, 0.25]], dtype=np.float64)
    rarity = np.asarray([2.0], dtype=np.float64)
    assert matched_score(similarity, plan, rarity) == pytest.approx(1.0)


# --- tiers ----------------------------------------------------------------


def test_tier_one_masks_the_padding() -> None:
    similarity = similarity_table(BANK, BANK, np.zeros(DIMENSION,
                                                       dtype=np.float32))
    rarity = np.ones(4, dtype=np.float64)
    scores = tier1_scores(similarity, rarity, INCIDENCE)
    assert scores.shape == (IMAGE_COUNT,)
    # Image c holds sea and sky alone, thus the lighthouse and cliff
    # atoms read their best value from those two and not from padding.
    assert np.isfinite(scores).all()


def test_an_image_with_no_element_raises() -> None:
    similarity = np.ones((1, 4), dtype=np.float32)
    empty = np.full((1, 3), -1, dtype=np.int32)
    with pytest.raises(ValueError, match="no element"):
        tier1_scores(similarity, np.ones(1), empty)
    with pytest.raises(ValueError, match="no element"):
        image_elements(empty, 0)


def test_the_channel_prefers_the_image_holding_the_rare_element() -> None:
    submission = _submission(("a lighthouse", BANK[0]))
    scores = element_channel(submission, _index(), CONFIG)
    assert scores.shape == (IMAGE_COUNT,)
    assert scores.dtype == np.float32
    assert int(np.argmax(scores)) == 0


def test_a_shortlist_of_one_leaves_the_other_images_on_tier_one() -> None:
    # An atom with a value against each element, so tier 1 and tier 2
    # give different numbers on the images below the shortlist.
    mixed = np.asarray([0.7, 0.5, 0.4, 0.3], dtype=np.float32)
    mixed /= np.linalg.norm(mixed)
    submission = _submission(("a tall shape by water", mixed))
    index = _index()
    exact = element_channel(submission, index, CONFIG)
    narrow = element_channel(submission, index,
                             CONFIG._replace(tier2_count=1))
    rarity = rarity_weights(
        similarity_table(np.stack([mixed]), BANK,
                         np.zeros(DIMENSION, dtype=np.float32)),
        FREQUENCY, IMAGE_COUNT)
    tier1 = tier1_scores(
        similarity_table(np.stack([mixed]), BANK,
                         np.zeros(DIMENSION, dtype=np.float32)),
        rarity, INCIDENCE)
    # The shortlist head gets the accurate matching in the two runs,
    # and the images below the boundary keep their tier-1 value.
    head = int(np.argmax(tier1))
    assert narrow[head] == pytest.approx(exact[head], abs=1e-6)
    others = [position for position in range(IMAGE_COUNT)
              if position != head]
    for position in others:
        assert narrow[position] == pytest.approx(tier1[position], abs=1e-6)
        assert narrow[position] != pytest.approx(exact[position], abs=1e-6)


def test_tier_one_is_a_maximum_of_the_accurate_score() -> None:
    # Tier 1 lets each atom read its best element with no competition,
    # thus it cannot fall below the matched score (R5).
    mixed = np.asarray([0.7, 0.5, 0.4, 0.3], dtype=np.float32)
    mixed /= np.linalg.norm(mixed)
    submission = _submission(("a tall shape by water", mixed),
                             ("the sea", BANK[2]))
    index = _index()
    stacked = np.stack([mixed, BANK[2]])
    similarity = similarity_table(stacked, BANK,
                                  np.zeros(DIMENSION, dtype=np.float32))
    rarity = rarity_weights(similarity, FREQUENCY, IMAGE_COUNT)
    tier1 = tier1_scores(similarity, rarity, INCIDENCE)
    exact = element_channel(submission, index, CONFIG)
    assert bool((exact <= tier1 + 1e-6).all())


def test_flooding_with_common_atoms_does_not_move_the_winner() -> None:
    # Architecture section 12.1: naming all of it does not help. The
    # five added atoms match elements in each image, thus their rarity
    # weight is zero and their pairings add nothing.
    lean = _submission(("a lighthouse", BANK[0]))
    flooded = _submission(("a lighthouse", BANK[0]),
                          *[("the sea", BANK[2]) for _ in range(3)],
                          *[("the sky", BANK[3]) for _ in range(2)])
    index = _index()
    assert int(np.argmax(element_channel(lean, index, CONFIG))) == 0
    assert int(np.argmax(element_channel(flooded, index, CONFIG))) == 0


def test_a_submission_with_no_text_atom_raises() -> None:
    empty = EncodedSubmission(atoms=(), vectors={})
    with pytest.raises(ValueError, match="needs one encoded DESCRIPTION"):
        element_channel(empty, _index(), CONFIG)


def test_an_alpha_below_one_raises() -> None:
    submission = _submission(("a lighthouse", BANK[0]))
    with pytest.raises(ValueError, match="not built"):
        element_channel(submission, _index(), CONFIG._replace(alpha=0.5))


def test_an_unknown_rule_raises() -> None:
    submission = _submission(("a lighthouse", BANK[0]))
    with pytest.raises(ValueError, match="comparison_rule"):
        element_channel(submission, _index(),
                        CONFIG._replace(comparison_rule="cosine"))
    with pytest.raises(ValueError, match="matching_rule"):
        element_channel(submission, _index(),
                        CONFIG._replace(matching_rule="hungarian"))


# --- the match report -----------------------------------------------------


def test_the_match_report_names_the_matched_element() -> None:
    submission = _submission(("a lighthouse", BANK[0]))
    rows = match_report(submission, _index(), 0, CONFIG)
    assert len(rows) == 1
    assert rows[0].atom_id == "a1"
    assert rows[0].atom_text == "a lighthouse"
    assert rows[0].element == "lighthouse"
    assert rows[0].similarity == pytest.approx(1.0)
    assert rows[0].rarity == pytest.approx(-math.log(1 / 3))
    assert rows[0].weight > 0.5


def test_an_atom_that_matches_nothing_reports_no_element() -> None:
    # Image c holds sea and sky. A lighthouse atom is orthogonal to the
    # two, thus no element holds more mass than staying unmatched and
    # the report names none of them.
    submission = _submission(("a lighthouse", BANK[0]))
    rows = match_report(submission, _index(), 2, CONFIG)
    assert rows[0].element is None
    assert rows[0].similarity == 0.0
    assert rows[0].weight > 0.0


def test_the_match_report_of_a_sketch_submission_is_empty() -> None:
    drawing = Atom(id="a1", type="WHOLE-DRAWING", subtype=None, text=None,
                   strokes=(((0.0, 0.0),),), refers_to=None, relation=None)
    submission = EncodedSubmission(
        atoms=(drawing,),
        vectors={"a1": np.zeros(DIMENSION, dtype=np.float32)})
    assert match_report(submission, _index(), 0, CONFIG) == ()
