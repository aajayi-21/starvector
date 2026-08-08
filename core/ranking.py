"""Layer 8 ranking: where did the target land?

Implements docs/ARCHITECTURE.md section 16 through
docs/specs/scoring-path.md section 10. This is the one module that
knows the target (Rule 1) — no module upstream references a target
identifier, and the test suite scans for that. The section 16 floor
D >= 200 binds frontload options — this phase has none.
"""

import numpy as np

from core.types import DecoySet, PoolIndex, PoolScores, TargetId, TrialScore


def _target_position(index: PoolIndex, target: TargetId) -> int:
    try:
        return index.image_ids.index(target)
    except ValueError:
        raise ValueError(
            f"target {target!r} is not a member of index "
            f"{index.index_id[:8]}") from None


def decoy_set(index: PoolIndex, target: TargetId) -> DecoySet:
    """The pool minus the target's full near-duplicate group.

    Rule 3 requires the removal: with near-duplicates of the target
    in the decoy set, encoder noise decides the rank in the trials
    where the player did best. Output: length-N boolean array, 1 for
    each decoy.
    """
    position = _target_position(index, target)
    group = index.group_ids[position]
    return np.asarray(np.array(index.group_ids) != group)   # (N,)


def rank(fused: PoolScores, target: TargetId, decoys: DecoySet,
         index: PoolIndex) -> TrialScore:
    """The trial score: p = (beaten + 0.5 * tied) / D (section 16).

    Equal float32 values give half credit. The index argument resolves
    the target identifier to its row — the one argument added to the
    CLAUDE.md section 5 shape (agreed 2026-08-08), pool-side data that
    stays in Layer 8.
    """
    position = _target_position(index, target)
    if fused.shape != (len(index.image_ids),):
        raise ValueError(
            f"fused must have shape ({len(index.image_ids)},), got "
            f"{fused.shape}")
    if decoys.shape != fused.shape:
        raise ValueError(
            f"decoys must have shape {fused.shape}, got {decoys.shape}")
    if bool(decoys[position]):
        raise ValueError("the decoy set must not contain the target")
    decoy_count = int(np.count_nonzero(decoys))
    if decoy_count == 0:
        raise ValueError("the decoy set is empty")
    target_score = fused[position]
    decoy_scores = fused[decoys]
    beaten = int(np.count_nonzero(decoy_scores < target_score))
    tied = int(np.count_nonzero(decoy_scores == target_score))
    p = (beaten + 0.5 * tied) / decoy_count
    return TrialScore(p=p, decoy_count=decoy_count, beaten=beaten, tied=tied)
