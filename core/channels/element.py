"""Layer 4 element channel: written atoms against pool element lists.

Implements docs/ARCHITECTURE.md section 12.1 through
docs/specs/element-channel.md section 8. A channel is a function of
(submission, pool): one number for each pool image, and the image that
hides behind the identifier is not an input (Rule 1). No provider, no
file access, no modality branch.

The score is rarity-weighted correspondence. An atom that matches an
element many images hold adds almost nothing, an atom that matches a
rare element adds much, and mass that matches nothing parks on a
reserve bin and does not invent a pairing.
"""

import math

import numpy as np

from core.types import (Atom, ElementConfig, EncodedSubmission, FloatArray,
                        Incidence, MatchRow, PoolIndex, PoolScores)

COMPARISON_RULES: tuple[str, ...] = ("element-center-cosine-v1",)
MATCHING_RULES: tuple[str, ...] = ("sinkhorn-slack-v1",)

# The alpha value the built path implements (D10). A lower value mixes
# a sketch vector into the atom side, and that path is not built.
BUILT_ALPHA = 1.0


def element_atoms(submission: EncodedSubmission) -> tuple[Atom, ...]:
    """The atoms this channel reads (spec P3 section 8.1).

    DESCRIPTION atoms that hold text and have a Layer 2 vector. A
    DESCRIPTION atom with strokes and no text has no vector at
    alpha 1.0 and takes no part. RELATION atoms do not enter (R2).
    """
    return tuple(atom for atom in submission.atoms
                 if atom.type == "DESCRIPTION" and atom.text is not None
                 and atom.id in submission.vectors)


def _checked_config(config: ElementConfig) -> None:
    """Stop on a configuration this module does not implement."""
    if config.comparison_rule not in COMPARISON_RULES:
        raise ValueError(
            f"unknown comparison_rule: {config.comparison_rule!r}")
    if config.matching_rule not in MATCHING_RULES:
        raise ValueError(f"unknown matching_rule: {config.matching_rule!r}")
    if config.epsilon <= 0.0 or not math.isfinite(config.epsilon):
        raise ValueError(f"epsilon must be positive, got {config.epsilon}")
    if config.sinkhorn_iterations < 1:
        raise ValueError(
            f"sinkhorn_iterations must be positive, got "
            f"{config.sinkhorn_iterations}")
    if config.tier2_count < 1:
        raise ValueError(
            f"tier2_count must be positive, got {config.tier2_count}")
    if config.alpha != BUILT_ALPHA:
        raise ValueError(
            f"alpha {config.alpha} is not built: the sketch-vector path "
            "behind values below 1.0 does not run in this phase (D10)")


def _centered(vectors: FloatArray, mean: FloatArray,
              name: str) -> tuple[FloatArray, FloatArray]:
    """Subtract the element-space mean and give the rows and norms.

    A zero norm after the subtraction means a vector equal to the mean.
    A silent zero or NaN there makes plausible numbers that are
    incorrect, so it raises (spec P2 R14).
    """
    if not np.isfinite(vectors).all():
        raise ValueError(f"{name} holds a non-finite value")
    centered = vectors - mean                                   # (rows, d)
    norms = np.linalg.norm(centered, axis=1)                    # (rows,)
    if bool((norms == 0.0).any()):
        raise ValueError(
            f"{name}: zero vector norm after mean subtraction")
    return centered, norms


def similarity_table(atom_vectors: FloatArray, element_vectors: FloatArray,
                     element_space_mean: FloatArray) -> FloatArray:
    """Rule element-center-cosine-v1 (D2): centered cosine, shape (m, k).

    Subtract the stored element-space mean from the two sides, then
    cosine on the centered rows. The subtraction removes the dominant
    average direction of the encoder space (architecture section 10),
    and mirrors the outline channel rule in element space (R7).
    """
    dimension = element_vectors.shape[1]
    if atom_vectors.ndim != 2 or atom_vectors.shape[1] != dimension:
        raise ValueError(
            f"atom_vectors must have shape (m, {dimension}), got "
            f"{atom_vectors.shape}")
    if element_space_mean.shape != (dimension,):
        raise ValueError(
            f"element_space_mean must have shape ({dimension},), got "
            f"{element_space_mean.shape}")
    atoms, atom_norms = _centered(atom_vectors, element_space_mean,
                                  "atom_vectors")
    elements, element_norms = _centered(element_vectors, element_space_mean,
                                        "element_vectors")
    products = atoms @ elements.T                               # (m, k)
    return products / np.outer(atom_norms, element_norms)       # (m, k)


def rarity_weights(pool_similarity: FloatArray,
                   pool_frequency: tuple[int, ...],
                   pool_image_count: int) -> FloatArray:
    """The rarity weight of each atom, in nats (R1, decision D1).

    pool_similarity is the (m, V) region of the similarity table that
    covers the pool vocabulary alone. Each atom takes the document
    frequency of the entry it matches best, and equal similarity values
    resolve to the lowest vocabulary index (the written rule of section
    15). rarity = -ln(document frequency / pool image count): an atom
    matching an element that appears everywhere gets a weight near
    zero, which is the intent — flooding the submission does not help
    (architecture section 12.1).

    Output shape (m,), float64.
    """
    if pool_image_count < 1:
        raise ValueError(
            f"pool_image_count must be positive, got {pool_image_count}")
    entry_count = len(pool_frequency)
    if pool_similarity.shape[1] != entry_count:
        raise ValueError(
            f"pool_similarity has {pool_similarity.shape[1]} columns, "
            f"expected {entry_count}")
    best = np.argmax(pool_similarity, axis=1)                   # (m,)
    frequencies = np.asarray(pool_frequency, dtype=np.float64)[best]
    if bool((frequencies < 1.0).any()):
        raise ValueError("a pool_frequency entry is below one")
    return -np.log(frequencies / float(pool_image_count))       # (m,)


def image_elements(incidence: Incidence, position: int) -> np.ndarray:
    """The vocabulary indices of one image, padding removed.

    incidence rows hold -1 in the empty places (spec P3 section 7).
    An image with no element cannot be given a score and raises,
    because a
    default value there is a plausible number that is incorrect.
    """
    row = incidence[position]                                   # (k,)
    kept = row[row >= 0]
    if kept.shape[0] == 0:
        raise ValueError(f"image at position {position} has no element")
    return kept


def tier1_scores(similarity: FloatArray, rarity: FloatArray,
                 incidence: Incidence) -> FloatArray:
    """Tier 1: each atom takes its best element, no competition (R5).

    A maximum approximation of the tier-2 score, and the shortlist
    ranking of architecture section 18. One collection through the
    incidence table plus a maximum: the atoms do not compete for
    elements, which makes tier 1 optimistic on purpose.

    similarity is (m, B), rarity is (m,), incidence is (N, k). Output
    shape (N,), float64.
    """
    valid = incidence >= 0                                      # (N, k)
    if not bool(valid.any(axis=1).all()):
        raise ValueError("an image has no element in the incidence table")
    safe = np.where(valid, incidence, 0)                        # (N, k)
    gathered = similarity[:, safe]                              # (m, N, k)
    masked = np.where(valid, gathered, -np.inf)                 # (m, N, k)
    best = masked.max(axis=2).astype(np.float64)                # (m, N)
    return (best * rarity[:, None]).sum(axis=0)                 # (N,)


def sinkhorn_plan(similarity: FloatArray, config: ElementConfig) -> np.ndarray:
    """The matching rule of D3: the plan, shape (m+1, k+1).

    The unbalanced relaxation of architecture section 12.1, written as
    reserve bins. One added row and one added column at similarity zero
    hold the mass that stays unmatched. Row totals are 1 for each atom
    and k for the reserve row. Column totals are 1 for each element and
    m for the reserve column. Each atom thus puts one unit of mass
    across the elements and the reserve column, and each element
    accepts one unit from the atoms and the reserve row. Forced
    complete matching can invent correspondence that the submission
    does not contain (R3).

    K = exp(C / epsilon), then a fixed count of alternating column and
    row rescalings. The count is fixed and is not a convergence test,
    because a convergence test makes the output a function of
    floating-point noise, and two runs must give equal bytes. At the
    pinned count the plan is deterministic and short of the limit, thus
    the sequence ends on a row rescaling: each atom then holds one unit
    of mass accurately, which is the quantity the score adds up, and no
    atom can contribute more than its rarity weight.
    """
    atom_count, element_count = similarity.shape
    if atom_count == 0 or element_count == 0:
        raise ValueError(
            f"similarity must not be empty, got {similarity.shape}")
    if not np.isfinite(similarity).all():
        raise ValueError("similarity holds a non-finite value")

    augmented = np.zeros((atom_count + 1, element_count + 1), dtype=np.float64)
    augmented[:atom_count, :element_count] = similarity
    kernel = np.exp(augmented / config.epsilon)   # (m+1, k+1)

    row_total = np.ones(atom_count + 1, dtype=np.float64)
    row_total[atom_count] = float(element_count)
    column_total = np.ones(element_count + 1, dtype=np.float64)
    column_total[element_count] = float(atom_count)

    row_scale = np.ones(atom_count + 1, dtype=np.float64)
    column_scale = np.ones(element_count + 1, dtype=np.float64)
    for _ in range(config.sinkhorn_iterations):
        column_scale = column_total / (kernel.T @ row_scale)
        row_scale = row_total / (kernel @ column_scale)
    return row_scale[:, None] * kernel * column_scale[None, :]


def soft_match(similarity: FloatArray, config: ElementConfig) -> np.ndarray:
    """The atom-by-element region of the plan, shape (m, k)."""
    atom_count, element_count = similarity.shape
    return sinkhorn_plan(similarity, config)[:atom_count, :element_count]


def shortlist_groups(shortlist: np.ndarray, incidence: Incidence,
                     ) -> tuple[tuple[np.ndarray, np.ndarray], ...]:
    """Split one shortlist by element count (P5 item B3).

    One group holds the shortlist positions with an equal element
    count k, in shortlist sequence, with their (S, k) column table -
    the row-sequence selection reproduces image_elements row by row,
    internal padding included. Equal counts make the batched
    computation padding-free, which is what keeps the batch
    byte-equal to the one-image path.
    """
    counts = (incidence[shortlist] >= 0).sum(axis=1)             # (S,)
    groups: list[tuple[np.ndarray, np.ndarray]] = []
    for count in np.unique(counts):
        if int(count) == 0:
            position = int(shortlist[counts == 0][0])
            raise ValueError(f"image at position {position} has no element")
        positions = shortlist[counts == count]                   # (S_k,)
        rows = incidence[positions]                              # (S_k, w)
        columns = rows[rows >= 0].reshape(len(positions), int(count))
        groups.append((positions, columns))
    return tuple(groups)


def sinkhorn_plans(tables: np.ndarray,
                   config: ElementConfig) -> np.ndarray:
    """The batched D3 plans, shape (S, m+1, k+1) float64.

    One stacked computation with the sinkhorn_plan steps: the same
    kernel construction, the same alternating rescalings through
    the matvec and vecmat forms, the same multiplication sequence.
    The output must equal sinkhorn_plan slice for slice
    byte-for-byte - the rescore rule (spec S1 R8) rides
    on it, and the equality test in
    tests/unit/test_element_batch.py is the standing gate on each
    machine the suite runs on.
    """
    if tables.ndim != 3:
        raise ValueError(f"tables must be 3-D, got {tables.shape}")
    batch, atom_count, element_count = tables.shape
    if batch == 0 or atom_count == 0 or element_count == 0:
        raise ValueError(f"tables must not be empty, got {tables.shape}")
    if not np.isfinite(tables).all():
        raise ValueError("tables holds a non-finite value")

    augmented = np.zeros((batch, atom_count + 1, element_count + 1),
                         dtype=np.float64)
    augmented[:, :atom_count, :element_count] = tables
    kernel = np.exp(augmented / config.epsilon)   # (S, m+1, k+1)

    row_total = np.ones(atom_count + 1, dtype=np.float64)
    row_total[atom_count] = float(element_count)
    column_total = np.ones(element_count + 1, dtype=np.float64)
    column_total[element_count] = float(atom_count)

    row_scale = np.ones((batch, atom_count + 1), dtype=np.float64)
    column_scale = np.ones((batch, element_count + 1), dtype=np.float64)
    for _ in range(config.sinkhorn_iterations):
        column_scale = column_total / np.vecmat(row_scale, kernel)
        row_scale = row_total / np.matvec(kernel, column_scale)
    return row_scale[:, :, None] * kernel * column_scale[:, None, :]


def soft_matches(tables: np.ndarray, config: ElementConfig) -> np.ndarray:
    """The atom-by-element regions of the batched plans, (S, m, k)."""
    batch, atom_count, element_count = tables.shape
    return sinkhorn_plans(tables, config)[:, :atom_count, :element_count]


def matched_scores(tables: np.ndarray, plans: np.ndarray,
                   rarity: FloatArray) -> np.ndarray:
    """The batched R4 scores, shape (S,) float64.

    The matched_score expression with the same association, and a
    row reduction that equals the flat sum byte-for-byte - the
    equality test is the gate.
    """
    product = plans * tables * rarity[None, :, None]             # (S, m, k)
    return product.reshape(product.shape[0], -1).sum(axis=1)     # (S,)


def matched_score(similarity: FloatArray, plan: np.ndarray,
                  rarity: FloatArray) -> float:
    """The channel score of one image (R4).

    The sum of plan * similarity * rarity across the atom and element
    axes. No precision-style penalty enters: by Rule 2 a term that
    depends on the submission alone cannot change the ranking
    (architecture section 12.1).
    """
    return float((plan * similarity * rarity[:, None]).sum())


def element_channel(submission: EncodedSubmission, index: PoolIndex,
                    config: ElementConfig) -> PoolScores:
    """Score the written atoms against each image's element list.

    Tier 1 runs across all images, tier 2 runs the accurate matching on
    the tier2_count best of them, and the tier-2 values replace their
    tier-1 values (D4). The two tiers measure the same quantity in the
    same units. With tier2_count at or above the image count, each
    image gets the accurate matching, which is the development value.

    Output shape (N,), float32.
    """
    _checked_config(config)
    atoms = element_atoms(submission)
    if not atoms:
        raise ValueError(
            "the element channel needs one encoded DESCRIPTION atom with "
            "text, got none")
    atom_vectors = np.stack([submission.vectors[atom.id] for atom in atoms])

    similarity = similarity_table(atom_vectors, index.vocabulary_vectors,
                                  index.element_space_mean)     # (m, B)
    entry_count = len(index.pool_frequency)
    rarity = rarity_weights(similarity[:, :entry_count],
                            index.pool_frequency,
                            index.pool_image_count)             # (m,)

    scores = tier1_scores(similarity, rarity, index.incidence)  # (N,)
    # Descending tier-1 value, equal values by ascending position: a
    # written rule, because the shortlist boundary must not follow from
    # the sort implementation.
    shortlist = np.argsort(-scores, kind="stable")[:config.tier2_count]
    for position in shortlist:
        columns = image_elements(index.incidence, int(position))
        table = similarity[:, columns]                          # (m, k)
        plan = soft_match(table, config)                        # (m, k)
        scores[position] = matched_score(table, plan, rarity)
    return scores.astype(np.float32)                            # (N,)


def match_report(submission: EncodedSubmission, index: PoolIndex,
                 position: int, config: ElementConfig) -> tuple[MatchRow, ...]:
    """One row for each atom against the image at position (D12).

    The architecture section 27 feedback shape. This runs after
    ranking, because the report needs a chosen image and the channel
    itself reads no such selection.

    An element is named only when it holds more matched mass than
    staying unmatched does. An atom that spreads its mass equally
    across elements it has no similarity with reports element None. To
    name the first of them states a correspondence the submission does
    not hold, which is the one thing a feedback screen must not do.
    """
    _checked_config(config)
    atoms = element_atoms(submission)
    if not atoms:
        return ()
    atom_vectors = np.stack([submission.vectors[atom.id] for atom in atoms])
    similarity = similarity_table(atom_vectors, index.vocabulary_vectors,
                                  index.element_space_mean)     # (m, B)
    entry_count = len(index.pool_frequency)
    rarity = rarity_weights(similarity[:, :entry_count],
                            index.pool_frequency,
                            index.pool_image_count)             # (m,)
    columns = image_elements(index.incidence, position)
    table = similarity[:, columns]                              # (m, k)
    plan = sinkhorn_plan(table, config)                         # (m+1, k+1)
    element_count = columns.shape[0]

    rows: list[MatchRow] = []
    for number, atom in enumerate(atoms):
        # Equal weights resolve to the lowest element position.
        best = int(np.argmax(plan[number, :element_count]))
        reserve = float(plan[number, element_count])
        parked = plan[number, best] <= reserve
        rows.append(MatchRow(
            atom_id=atom.id,
            atom_text=atom.text or "",
            element=None if parked else index.vocabulary[int(columns[best])],
            weight=reserve if parked else float(plan[number, best]),
            similarity=0.0 if parked else float(table[number, best]),
            rarity=float(rarity[number]),
        ))
    return tuple(rows)
