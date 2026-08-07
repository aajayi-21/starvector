"""Pure rule for stage s05: salient object fraction (R6).

Spec: docs/specs/pool-curation.md section 10, s05.
"""

from collections.abc import Sequence

from core.canonical import quantize_measured
from core.types import FloatArray
from pool.curation.types import Rejection, StageResult

_STAGE = "s05-object"


def object_decisions(
    image_ids: Sequence[str], fractions: FloatArray, min_object_fraction: float
) -> StageResult[str]:
    """Apply R6: reject when the fraction is at or below the limit.

    fractions is float32 with shape (N,), index-aligned with image_ids.
    The rule quantizes each value to float64 first. Thus the compared
    value and the stored measured value are equal, and a value equal to
    the limit is a rejection. A fraction of zero is a rejection - the
    R6 rule applied literally, not a fallback. Survivors keep the input
    sequence.
    """
    if fractions.shape != (len(image_ids),):
        raise ValueError(
            f"fractions shape {fractions.shape} does not agree with "
            f"{len(image_ids)} image ids"
        )
    survivors: list[str] = []
    rejections: list[Rejection] = []
    for image_id, raw_value in zip(image_ids, fractions.tolist(), strict=True):
        value = quantize_measured(raw_value)
        if value <= min_object_fraction:
            rejections.append(
                Rejection(
                    key=image_id,
                    stage=_STAGE,
                    reason="object-size",
                    measured=value,
                    detail="",
                )
            )
        else:
            survivors.append(image_id)
    return StageResult(survivors=tuple(survivors), rejections=tuple(rejections))
