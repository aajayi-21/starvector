"""Pure rule for the person screen of stage s05 (owner ruling 2026-11-03).

Spec: docs/specs/production-pool.md section 5a. An image of one person
or one face goes out of the pool. A person in a scene stays. The rule
runs in curation, before a target is on file, thus the target and the
decoys have one path (I3).
"""

from collections.abc import Sequence

from core.types import FloatArray
from pool.curation.types import Rejection, StageResult

_STAGE = "s05-object"


def person_decisions(image_ids: Sequence[str],
                     main_subject: FloatArray) -> StageResult[str]:
    """Reject each image with the flag at 1. Survivors keep the sequence.

    main_subject is float32 with shape (N,), index-aligned with image_ids.
    """
    if main_subject.shape != (len(image_ids),):
        raise ValueError(
            f"main_subject shape {main_subject.shape} does not agree with "
            f"{len(image_ids)} image ids"
        )
    survivors: list[str] = []
    rejections: list[Rejection] = []
    for image_id, flag in zip(image_ids, main_subject.tolist(), strict=True):
        if flag > 0.0:
            rejections.append(Rejection(key=image_id, stage=_STAGE,
                                        reason="person-focus", measured=flag,
                                        detail=""))
        else:
            survivors.append(image_id)
    return StageResult(survivors=tuple(survivors), rejections=tuple(rejections))
