"""Stage s06 near-duplicate removal. Pure decision logic on arrays.

Spec: docs/specs/pool-curation.md section 10, stage s06, and decision
D5. Architecture rule R7 sets the similarity threshold. The runner does
all I/O and encoding. This module only decides.
"""

from collections.abc import Sequence

import numpy as np

from core.canonical import quantize_measured
from core.types import Vectors
from pool.curation.types import Rejection, StageResult

STAGE = "s06-neardup"


def neardup_decisions(
    image_ids: Sequence[str],
    areas: Sequence[int],
    vectors: Vectors,
    similarity_threshold: float,
) -> StageResult[str]:
    """Apply the D5 greedy keep rule to one aligned candidate set.

    The walk sequence sorts candidates by pixel area, largest first,
    then by ascending image_id. The walk keeps the first candidate.
    For each candidate after it, the walk calculates the cosine
    similarity to the kept vectors in float32, and casts the maximum
    to float64. A maximum at or above the threshold makes the
    candidate a rejection with cause "near-duplicate", the quantized
    similarity as the measured value, and the nearest kept image_id as
    the recorded neighbor. On equal similarities the earliest kept
    candidate is the recorded neighbor.

    Arguments:
        image_ids: N image identifiers.
        areas: N pixel areas (width times height), aligned with image_ids.
        vectors: float32 (N, d), unit-norm rows, aligned with image_ids.
        similarity_threshold: the R7 limit from the stage config.

    The output holds survivors sorted by ascending image_id, and
    rejections in walk sequence.
    """
    count = len(image_ids)
    if len(areas) != count:
        raise ValueError(f"areas length {len(areas)} does not match image_ids length {count}")
    if vectors.ndim != 2 or vectors.shape[0] != count:
        raise ValueError(f"vectors shape {vectors.shape} does not match {count} candidates")
    if vectors.dtype != np.float32:
        raise ValueError(f"vectors dtype {vectors.dtype} is not float32")

    # The similarity values have float32 precision. The threshold gets
    # the same precision, and thus a cosine equal to the float32 value
    # of the threshold counts as a rejection.
    threshold = float(np.float32(similarity_threshold))

    walk = sorted(range(count), key=lambda index: (-areas[index], image_ids[index]))
    kept: list[int] = []
    rejections: list[Rejection] = []
    for index in walk:
        if kept:
            similarities = vectors[kept] @ vectors[index]  # (K,) float32
            nearest = int(np.argmax(similarities))  # equal values: earliest kept
            similarity = float(similarities[nearest])  # float32 cast to float64
            if similarity >= threshold:
                rejections.append(
                    Rejection(
                        key=image_ids[index],
                        stage=STAGE,
                        reason="near-duplicate",
                        measured=quantize_measured(similarity),
                        detail=image_ids[kept[nearest]],
                    )
                )
                continue
        kept.append(index)

    survivors = tuple(sorted(image_ids[index] for index in kept))
    return StageResult(survivors=survivors, rejections=tuple(rejections))
