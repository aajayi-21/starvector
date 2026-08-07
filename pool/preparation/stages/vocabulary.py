"""Stage p04 vocabulary construction. Pure pool-level functions.

Spec: docs/specs/pool-preparation.md section 10, stage p04.
Architecture rules R4, R5, and R6 give the artifacts, and decision
D11 gives the mean. The runner encodes the entries and writes the
arrays - this module only builds.
"""

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

from core.types import FloatArray, Vectors


def vocabulary_build(capped: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """The pool vocabulary: sorted deduplicated capped element strings.

    Ascending lexicographic sequence fixes the indices (R6, spec
    section 14).
    """
    return tuple(sorted({element for sequence in capped for element in sequence}))


def vocabulary_frequencies(
    vocabulary: Sequence[str], capped: Sequence[Sequence[str]]
) -> tuple[int, ...]:
    """pool_frequency for each vocabulary entry, aligned with vocabulary.

    The frequency is the count of images with the entry in their
    capped element list - an image counts one time. An element not in
    the vocabulary raises ValueError (R14).
    """
    counts = {element: 0 for element in vocabulary}
    for sequence in capped:
        for element in set(sequence):
            if element not in counts:
                raise ValueError(f"element {element!r} is not in the vocabulary")
            counts[element] += 1
    return tuple(counts[element] for element in vocabulary)


def vocabulary_incidence(
    image_ids: Sequence[str],
    capped: Sequence[Sequence[str]],
    vocabulary: Sequence[str],
    max_elements: int,
) -> NDArray[np.int32]:
    """The R6 incidence table: vocabulary indices for each pool image.

    The output is int32 with shape (N, max_elements). Rows follow
    image_ids, entries follow the capped element sequence, and the
    pad entries hold -1. An element not in the vocabulary, or a sequence
    longer than max_elements, raises ValueError (R14).
    """
    count = len(image_ids)
    if len(capped) != count:
        raise ValueError(
            f"capped length {len(capped)} does not agree with image_ids length {count}"
        )
    index = {element: position for position, element in enumerate(vocabulary)}
    table = np.full((count, max_elements), -1, dtype=np.int32)
    for row, sequence in enumerate(capped):
        entries = list(sequence)
        if len(entries) > max_elements:
            raise ValueError(
                f"image {image_ids[row]} has {len(entries)} elements, more than "
                f"the cap {max_elements}"
            )
        for column, element in enumerate(entries):
            if element not in index:
                raise ValueError(f"element {element!r} is not in the vocabulary")
            table[row, column] = index[element]
    return table


def vector_mean(vectors: Vectors) -> FloatArray:
    """The raw D11 mean of one vector population.

    Accumulates in float64, then casts to float32. The input is
    (M, d) with M of 1 or more. The output is (d,). The raw mean is
    stored, not a unit-norm copy - Layer 2 code applies it when
    vectors are compared (R9).
    """
    if vectors.ndim != 2 or vectors.shape[0] < 1:
        raise ValueError(f"vectors shape {vectors.shape} is not (M, d) with M >= 1")
    return vectors.astype(np.float64).mean(axis=0).astype(np.float32)
