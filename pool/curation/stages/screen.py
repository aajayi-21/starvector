"""Pure rules for stage s01: R2 and R3 on claimed metadata.

Spec: docs/specs/pool-curation.md section 10, s01. This stage checks
the claimed dimensions only. Stage s02 checks the decoded pixels, which
are authoritative. Candidates without claimed dimensions go through.
"""

from collections.abc import Sequence

from core.canonical import quantize_measured
from pool.curation.config import ScreenSection
from pool.curation.types import CandidateRecord, Rejection, StageResult

_STAGE = "s01-screen"


def _claimed_rejection(
    candidate: CandidateRecord, screen: ScreenSection
) -> Rejection | None:
    """The R2 or R3 rejection for one candidate, or None.

    R2 comes first. A candidate that breaks R2 and R3 at the same time
    gets the R2 rejection only.
    """
    width = candidate.claimed_width
    height = candidate.claimed_height
    if width is None or height is None:
        return None
    short_side = min(width, height)
    if short_side < screen.min_short_side:
        return Rejection(
            key=candidate.source_key,
            stage=_STAGE,
            reason="resolution-metadata",
            measured=float(short_side),
            detail="",
        )
    aspect = width / height
    if aspect < screen.min_aspect or aspect > screen.max_aspect:
        return Rejection(
            key=candidate.source_key,
            stage=_STAGE,
            reason="aspect-metadata",
            measured=quantize_measured(aspect),
            detail="",
        )
    return None


def screen_decisions(
    candidates: Sequence[CandidateRecord], screen: ScreenSection
) -> StageResult[CandidateRecord]:
    """Apply R2 and R3 to the claimed dimensions of each candidate.

    The R3 range is inclusive - a value equal to a limit stays.
    Survivors keep the input sequence. One candidate gets at most one
    rejection.
    """
    survivors: list[CandidateRecord] = []
    rejections: list[Rejection] = []
    for candidate in candidates:
        rejection = _claimed_rejection(candidate, screen)
        if rejection is None:
            survivors.append(candidate)
        else:
            rejections.append(rejection)
    return StageResult(survivors=tuple(survivors), rejections=tuple(rejections))
