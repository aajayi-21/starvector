"""The P5 R3 gate: the batched tier 2 equals the loop, byte for byte.

The stored trial rows came from the one-image path, and the rescore
rule (spec S1 R8) rides on accurate bytes. These tests compare
the batched functions against the one-image functions on randomized
fixtures and assert equal bytes - they are the standing gate on each
machine the suite runs on. If a numpy or BLAS change breaks the
equality, the committed fallback is the one-image path in the
hoisted batch (spec P5 R3: a diverging batch stops the work).
"""

import numpy as np
import pytest

from core.channels.element import (image_elements, matched_score,
                                   matched_scores, shortlist_groups,
                                   sinkhorn_plan, sinkhorn_plans, soft_match,
                                   soft_matches)
from core.types import ElementConfig


def _config(epsilon: float = 0.1, iterations: int = 20) -> ElementConfig:
    return ElementConfig(comparison_rule="element-center-cosine-v1",
                         matching_rule="sinkhorn-slack-v1",
                         epsilon=epsilon, sinkhorn_iterations=iterations,
                         tier2_count=500, alpha=1.0)


def _tables(seed: int, batch: int, atoms: int, elements: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # Cosine-scaled float32, the production table dtype and range.
    raw = rng.uniform(-1.0, 1.0, size=(batch, atoms, elements))
    return raw.astype(np.float32)


def test_batched_plans_equal_the_loop_plans_byte_for_byte() -> None:
    for seed, atoms in enumerate((1, 2, 5, 10)):
        for elements in (1, 2, 7, 19, 20):
            for epsilon in (0.05, 0.1, 0.5):
                for iterations in (1, 20):
                    config = _config(epsilon, iterations)
                    tables = _tables(seed, 7, atoms, elements)
                    stacked = sinkhorn_plans(tables, config)
                    for index in range(tables.shape[0]):
                        one = sinkhorn_plan(tables[index], config)
                        assert stacked[index].tobytes() == one.tobytes()


def test_batched_scores_equal_the_loop_scores_byte_for_byte() -> None:
    rng = np.random.default_rng(3)
    config = _config()
    for atoms, elements in ((1, 1), (2, 7), (8, 20)):
        tables = _tables(atoms, 9, atoms, elements)
        rarity = rng.uniform(0.1, 5.0, size=atoms)               # float64
        plans = soft_matches(tables, config)
        batched = matched_scores(tables, plans, rarity)
        for index in range(tables.shape[0]):
            one = matched_score(tables[index],
                                soft_match(tables[index], config), rarity)
            assert batched[index].tobytes() == np.float64(one).tobytes()


def test_mixed_shortlists_group_and_equal_the_loop() -> None:
    # The end-to-end property: a randomized incidence with mixed
    # element counts, an internal-padding row, and a one-image
    # group. The grouped batch must reproduce the one-image loop.
    rng = np.random.default_rng(11)
    config = _config()
    image_count, width, vocabulary = 40, 20, 120
    incidence = np.full((image_count, width), -1, dtype=np.int32)
    for row in range(image_count):
        count = int(rng.integers(1, width + 1))
        entries = rng.choice(vocabulary, size=count, replace=False)
        incidence[row, :count] = entries
    # One internal-padding row: the channel tolerates it, thus the
    # batch cannot quietly diverge from the loop there.
    incidence[5] = -1
    incidence[5, 0] = 3
    incidence[5, 7] = 9
    atoms = 4
    similarity = rng.uniform(-1.0, 1.0,
                             size=(atoms, vocabulary)).astype(np.float32)
    rarity = rng.uniform(0.1, 5.0, size=atoms)
    shortlist = np.argsort(rng.standard_normal(image_count),
                           kind="stable")[:25]

    loop_scores = {}
    for position in shortlist:
        columns = image_elements(incidence, int(position))
        table = similarity[:, columns]
        plan = soft_match(table, config)
        loop_scores[int(position)] = matched_score(table, plan, rarity)

    for positions, columns in shortlist_groups(shortlist, incidence):
        tables = similarity[:, columns].transpose(1, 0, 2)       # (S, m, k)
        plans = soft_matches(tables, config)
        batched = matched_scores(tables, plans, rarity)
        for index, position in enumerate(positions):
            expected = np.float64(loop_scores[int(position)])
            assert batched[index].tobytes() == expected.tobytes()
            assert np.float32(batched[index]).tobytes() \
                == np.float32(expected).tobytes()


def test_shortlist_groups_keep_the_shortlist_sequence() -> None:
    incidence = np.array([[1, 2, -1], [3, -1, -1], [4, 5, -1],
                          [6, -1, -1], [7, 8, 9]], dtype=np.int32)
    shortlist = np.array([4, 2, 0, 3, 1])
    groups = shortlist_groups(shortlist, incidence)
    seen = []
    for positions, columns in groups:
        count = columns.shape[1]
        assert all((incidence[p] >= 0).sum() == count for p in positions)
        # In one group the shortlist sequence holds.
        order = [int(np.where(shortlist == p)[0][0]) for p in positions]
        assert order == sorted(order)
        seen.extend(int(p) for p in positions)
    assert sorted(seen) == sorted(int(p) for p in shortlist)


def test_a_shortlist_image_with_no_element_raises() -> None:
    incidence = np.array([[1, 2], [-1, -1]], dtype=np.int32)
    with pytest.raises(ValueError, match="no element"):
        shortlist_groups(np.array([0, 1]), incidence)


def test_the_channel_equals_the_one_image_reference_loop() -> None:
    # The channel-level pin: element_channel after the switch equals
    # a reference that reruns tier 1 plus the one-image loop - the
    # reference IS the code from before the change, thus this test
    # proves before-and-after byte equality with no stored golden
    # file.
    from core.channels.element import (element_atoms, element_channel,
                                       rarity_weights, similarity_table,
                                       tier1_scores)
    from core.types import Atom, EncodedSubmission, PoolIndex

    rng = np.random.default_rng(23)
    image_count, width, vocabulary_count, dimension = 30, 6, 60, 12
    incidence = np.full((image_count, width), -1, dtype=np.int32)
    for row in range(image_count):
        count = int(rng.integers(1, width + 1))
        incidence[row, :count] = rng.choice(vocabulary_count, size=count,
                                            replace=False)
    vocabulary_vectors = rng.standard_normal(
        (vocabulary_count, dimension)).astype(np.float32)
    mean = rng.standard_normal(dimension).astype(np.float32) * 0.1
    index = PoolIndex(
        index_id="e" * 64,
        image_ids=tuple(f"{i:064x}" for i in range(image_count)),
        outline_vectors=np.ones((image_count, 6, dimension),
                                dtype=np.float32),
        outline_space_mean=np.zeros(dimension, dtype=np.float32),
        group_ids=tuple(f"{i:064x}" for i in range(image_count)),
        pool_image_count=image_count,
        vocabulary=tuple(f"element {i}" for i in range(vocabulary_count)),
        pool_frequency=tuple(int(v) for v in
                             rng.integers(1, image_count,
                                          size=vocabulary_count)),
        vocabulary_vectors=vocabulary_vectors,
        incidence=incidence,
        element_space_mean=mean,
        box_table=np.zeros((image_count, width, 4), dtype=np.float32),
        box_mask=np.zeros((image_count, width), dtype=bool),
    )
    atoms = tuple(
        Atom(id=f"a{n}", type="DESCRIPTION", subtype=None,
             text=f"atom {n}", strokes=None, refers_to=None, relation=None)
        for n in range(1, 4))
    vectors = {atom.id: rng.standard_normal(dimension).astype(np.float32)
               for atom in atoms}
    submission = EncodedSubmission(atoms=atoms, vectors=vectors)
    config = _config()

    channel = element_channel(submission, index, config)

    atom_vectors = np.stack([vectors[a.id] for a in element_atoms(submission)])
    similarity = similarity_table(atom_vectors, vocabulary_vectors, mean)
    rarity = rarity_weights(similarity, index.pool_frequency, image_count)
    reference = tier1_scores(similarity, rarity, incidence)
    shortlist = np.argsort(-reference, kind="stable")[:config.tier2_count]
    for position in shortlist:
        columns = image_elements(incidence, int(position))
        table = similarity[:, columns]
        plan = soft_match(table, config)
        reference[position] = matched_score(table, plan, rarity)

    assert channel.tobytes() == reference.astype(np.float32).tobytes()
