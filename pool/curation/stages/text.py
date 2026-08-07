"""Pure rule for stage s03: text coverage (R4).

Spec: docs/specs/pool-curation.md section 10, s03.
"""

from collections.abc import Sequence

from core.canonical import quantize_measured
from core.types import FloatArray
from pool.curation.types import Rejection, StageResult

_STAGE = "s03-text"


def text_decisions(
    image_ids: Sequence[str], coverage: FloatArray, max_text_coverage: float
) -> StageResult[str]:
    """Apply R4: reject when text coverage is more than the limit.

    coverage is float32 with shape (N,), index-aligned with image_ids.
    The rule quantizes each value to float64 first. Thus the compared
    value and the stored measured value are equal, and a value equal to
    the limit stays. Survivors keep the input sequence, which callers
    give in ascending image_id.
    """
    if coverage.shape != (len(image_ids),):
        raise ValueError(
            f"coverage shape {coverage.shape} does not agree with "
            f"{len(image_ids)} image ids"
        )
    survivors: list[str] = []
    rejections: list[Rejection] = []
    for image_id, raw_value in zip(image_ids, coverage.tolist(), strict=True):
        value = quantize_measured(raw_value)
        if value > max_text_coverage:
            rejections.append(
                Rejection(
                    key=image_id,
                    stage=_STAGE,
                    reason="text-coverage",
                    measured=value,
                    detail="",
                )
            )
        else:
            survivors.append(image_id)
    return StageResult(survivors=tuple(survivors), rejections=tuple(rejections))
