"""Stage p03 element cap. Pure pool-level rarity selection.

Spec: docs/specs/pool-preparation.md section 10, stage p03, and
decisions D7 and D8. Architecture rule R3 sets the cap. The document
frequency the pool itself defines drives the selection - no model.
"""

import math
from collections.abc import Mapping, Sequence

from core.canonical import quantize_measured
from pool.preparation.types import CutRecord


def cap_decisions(
    image_ids: Sequence[str],
    element_sequences: Sequence[Sequence[str]],
    max_elements: int,
) -> tuple[tuple[tuple[str, ...], ...], tuple[CutRecord, ...]]:
    """Apply the R3 cap to the aligned element sequences of one pool.

    For each element, df is the count of images with that element in
    their p02 sequence - an image counts one time. The capping rarity
    is the negative natural logarithm of df / N. An image with more
    than max_elements entries keeps the max_elements entries with the
    highest capping rarity. On equal df values the earlier flatten
    position is kept (D8). Kept entries keep their p02 relative
    sequence - selection is by rarity, presentation stays in flatten
    sequence. Cut entries become CutRecord rows sorted by image_id,
    then by position, with the quantized rarity and the measured df.

    Arguments:
        image_ids: N unique image identifiers, ascending.
        element_sequences: N element sequences, aligned with image_ids.
        max_elements: the R3 cap from the stage config.

    The output is a pair: the capped sequences aligned with
    image_ids, and the CutRecord rows.
    """
    count = len(image_ids)
    if len(element_sequences) != count:
        raise ValueError(
            f"element_sequences length {len(element_sequences)} does not agree "
            f"with image_ids length {count}"
        )
    ids = list(image_ids)
    if any(ids[index] >= ids[index + 1] for index in range(count - 1)):
        raise ValueError("image_ids must be strictly ascending")
    if max_elements < 1:
        raise ValueError(f"max_elements {max_elements} is not positive")

    df: dict[str, int] = {}
    for sequence in element_sequences:
        for element in set(sequence):
            df[element] = df.get(element, 0) + 1

    return cap_with_frequencies(ids, element_sequences, max_elements, df,
                                count)


def cap_with_frequencies(
    image_ids: Sequence[str],
    element_sequences: Sequence[Sequence[str]],
    max_elements: int,
    df_of: Mapping[str, int],
    image_count: int,
) -> tuple[tuple[tuple[str, ...], ...], tuple[CutRecord, ...]]:
    """The R3 cap with the document frequencies given, not measured.

    cap_decisions measures df across the sequences it caps, which is
    the pool definition. The V1 union side caps photograph element
    lists against the pool's frequencies, because rarity is
    pool-defined and a set of 200 photographs is not the pool (spec P3
    decision D8). An element the mapping does not name is unknown to
    the pool and takes frequency 1 — it appears nowhere there, which is
    the rarest an element can be.

    Arguments:
        image_ids: unique image identifiers, ascending.
        element_sequences: element sequences, aligned with image_ids.
        max_elements: the R3 cap from the stage config.
        df_of: the document frequency of each known element.
        image_count: the image count across which the frequencies range.
    """
    if image_count < 1:
        raise ValueError(f"image_count {image_count} is not positive")
    if max_elements < 1:
        raise ValueError(f"max_elements {max_elements} is not positive")
    ids = list(image_ids)
    capped: list[tuple[str, ...]] = []
    cuts: list[CutRecord] = []
    for image_id, sequence in zip(ids, element_sequences):
        df = {element: df_of.get(element, 1) for element in sequence}
        entries = list(sequence)
        if len(entries) <= max_elements:
            capped.append(tuple(entries))
            continue
        # Equal df means equal capping rarity, and thus the sort key
        # uses df directly - no float equality enters the selection.
        # The position key applies the D8 rule.
        ranked = sorted(range(len(entries)), key=lambda position: (df[entries[position]], position))
        kept_positions = set(ranked[:max_elements])
        capped.append(
            tuple(entries[position] for position in range(len(entries))
                  if position in kept_positions)
        )
        for position in range(len(entries)):
            if position in kept_positions:
                continue
            element = entries[position]
            cuts.append(
                CutRecord(
                    image_id=image_id,
                    element=element,
                    df=df[element],
                    capping_rarity=quantize_measured(
                        -math.log(df[element] / image_count)),
                )
            )
    return tuple(capped), tuple(cuts)
