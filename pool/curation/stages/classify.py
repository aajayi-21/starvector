"""Pure rules for stage s04: zero-shot classification (R5).

Spec: docs/specs/pool-curation.md section 10, s04, and open decisions
D1 and D2. A candidate stays only when the keep label wins the argmax.
"""

from collections.abc import Sequence

import numpy as np

from core.canonical import quantize_measured
from core.types import FloatArray
from pool.curation.types import Rejection, StageResult

_STAGE = "s04-class"


def rendered_labels(labels: Sequence[str], template: str) -> tuple[str, ...]:
    """Fill the label template with each label, in label sequence."""
    return tuple(template.replace("{label}", label) for label in labels)


def reason_for_label(label: str) -> str:
    """The rejection cause for one winning label.

    Spaces in the label become hyphens, and the prefix is "class-".
    """
    return "class-" + label.replace(" ", "-")


def class_decisions(
    image_ids: Sequence[str],
    probabilities: FloatArray,
    labels: Sequence[str],
    keep_label: str,
) -> StageResult[str]:
    """Apply R5: keep a candidate only when keep_label is the argmax.

    probabilities is float32 with shape (N, L): one row for each image
    id, one column for each label. On equal winning values, the lowest
    label index wins (numpy argmax). A rejection stores the winning
    label's probability, quantized. Survivors keep the input sequence.
    """
    if keep_label not in labels:
        raise ValueError(f"keep_label {keep_label!r} is not in labels")
    if probabilities.shape != (len(image_ids), len(labels)):
        raise ValueError(
            f"probabilities shape {probabilities.shape} does not agree with "
            f"{len(image_ids)} image ids and {len(labels)} labels"
        )
    winners = np.argmax(probabilities, axis=1)  # (N,) lowest winning index for each row
    survivors: list[str] = []
    rejections: list[Rejection] = []
    for row, image_id in enumerate(image_ids):
        winner_index = int(winners[row])
        winner = labels[winner_index]
        if winner == keep_label:
            survivors.append(image_id)
        else:
            rejections.append(
                Rejection(
                    key=image_id,
                    stage=_STAGE,
                    reason=reason_for_label(winner),
                    measured=quantize_measured(float(probabilities[row, winner_index])),
                    detail="",
                )
            )
    return StageResult(survivors=tuple(survivors), rejections=tuple(rejections))
