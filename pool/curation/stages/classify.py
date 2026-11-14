"""Pure rules for stage s04: zero-shot classification (R5).

Spec: docs/specs/pool-curation.md section 10, s04, and open decisions
D1 and D2. A candidate stays only when the keep label alone holds the
highest value of its row.
"""

from collections.abc import Sequence

import numpy as np

from core.canonical import quantize_measured
from core.types import FloatArray
from pool.curation.types import Rejection, StageResult

_STAGE = "s04-class"
NO_WINNER_REASON = "class-no-winner"


def rendered_labels(labels: Sequence[str], template: str) -> tuple[str, ...]:
    """Fill the label template with each label, in label sequence."""
    return tuple(template.replace("{label}", label) for label in labels)


def reason_for_label(label: str) -> str:
    """The rejection cause for one winning label.

    Spaces in the label become hyphens, and the prefix is "class-".
    """
    return "class-" + label.replace(" ", "-")


def winning_label(row: FloatArray, labels: Sequence[str]) -> str | None:
    """The one label with the highest value of a row, or None.

    row has shape (L,), in label sequence. When two or more labels have
    the highest value, the row has no winner and the output is None. The
    function compares the values as stored, with no tolerance.
    """
    if row.shape != (len(labels),):
        raise ValueError(
            f"row shape {row.shape} does not agree with {len(labels)} labels")
    highest = np.flatnonzero(row == row.max())  # (k,) each index at the top value
    if len(highest) != 1:
        return None
    return labels[int(highest[0])]


def class_decisions(
    image_ids: Sequence[str],
    probabilities: FloatArray,
    labels: Sequence[str],
    keep_label: str,
) -> StageResult[str]:
    """Apply R5: keep a candidate only when keep_label alone wins its row.

    probabilities is float32 with shape (N, L): one row for each image
    id, one column for each label. A row where two or more labels have
    the highest value has no winner, and its candidate goes out with
    the cause class-no-winner (spec P1a section 10, the s04 note of
    2026-11-11). A row with no information must not keep a candidate
    because the keep label is first in the label sequence. A rejection
    stores the highest probability of its row, quantized. Survivors
    keep the input sequence.
    """
    if keep_label not in labels:
        raise ValueError(f"keep_label {keep_label!r} is not in labels")
    if probabilities.shape != (len(image_ids), len(labels)):
        raise ValueError(
            f"probabilities shape {probabilities.shape} does not agree with "
            f"{len(image_ids)} image ids and {len(labels)} labels"
        )
    survivors: list[str] = []
    rejections: list[Rejection] = []
    for row, image_id in enumerate(image_ids):
        winner = winning_label(probabilities[row], labels)
        if winner == keep_label:
            survivors.append(image_id)
            continue
        reason = NO_WINNER_REASON if winner is None else reason_for_label(winner)
        rejections.append(
            Rejection(
                key=image_id,
                stage=_STAGE,
                reason=reason,
                measured=quantize_measured(float(probabilities[row].max())),
                detail="",
            )
        )
    return StageResult(survivors=tuple(survivors), rejections=tuple(rejections))
