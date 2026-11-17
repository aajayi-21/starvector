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


def _candidate_counts(row: np.ndarray, multi: list[np.ndarray],
                      ) -> tuple[np.ndarray, np.ndarray]:
    """For one player, beaten and tied at each candidate target. Shapes (N,).

    beaten[t] counts the decoys of t below the score at t, and tied[t]
    the decoys of t equal to it, with the decoys of t the pool minus
    the near-duplicate group of t, as decoy_set gives. The counts in
    the full pool come from one sort. The members of a group of two or
    more are not decoys of each other, thus their counts in the group
    come off.
    """
    ordered = np.sort(row)                                     # (N,)
    below = np.searchsorted(ordered, row, side="left")         # (N,)
    equal = np.searchsorted(ordered, row, side="right") - below
    for members in multi:
        values = row[members]                                  # (G,)
        in_order = np.sort(values)
        below[members] -= np.searchsorted(in_order, values, side="left")
        equal[members] -= (np.searchsorted(in_order, values, side="right")
                           - np.searchsorted(in_order, values, side="left"))
    # equal counted t itself in the pool and in a group of two or more.
    # A group of one did not come off, thus t comes off here.
    single = np.ones(len(row), dtype=bool)
    for members in multi:
        single[members] = False
    equal[single] -= 1
    return below, equal


def day_rank(scores: np.ndarray, target: TargetId, index: PoolIndex) -> float:
    """The day rank of spec AG1 section 5: where the target's day number lands.

    scores holds the fused pool scores of the day's players, shape
    (players, N), one row for each player. For each candidate t of the
    pool, each player gets the corrected score of Layer 9 with t as the
    target, (beaten + 0.5 tied + 0.5) / (D_t + 1), and the day number
    A(t) is their mean. The day rank is

        (#{t : A(t) < A(target)} + 0.5 #{t != target : A(t) = A(target)}
         + 0.5) / N

    With no skill the target is an equally likely member of the pool
    and has no connection with the submissions, thus the day rank is
    flat whatever the correlation of the players. This module is the
    one that knows the target (Rule 1), thus the rank is made here and
    Layer 9 reads the number alone.
    """
    position = _target_position(index, target)
    count = len(index.image_ids)
    if scores.ndim != 2 or scores.shape[1] != count or scores.shape[0] < 1:
        raise ValueError(
            f"scores must have shape (players, {count}) with one or more "
            f"players, got {scores.shape}")
    if not np.all(np.isfinite(scores)):
        raise ValueError("scores must be finite")
    groups = np.asarray(index.group_ids)
    _, inverse, sizes = np.unique(groups, return_inverse=True,
                                  return_counts=True)
    multi = [np.flatnonzero(inverse == label)
             for label in np.flatnonzero(sizes > 1)]
    decoy_counts = count - sizes[inverse]                       # (N,)
    if np.any(decoy_counts < 1):
        raise ValueError("a candidate has an empty decoy set")
    total = np.zeros(count, dtype=np.float64)                   # (N,)
    for row in scores:
        beaten, tied = _candidate_counts(row, multi)
        total += (beaten + 0.5 * tied + 0.5) / (decoy_counts + 1)
    days = total / scores.shape[0]                              # (N,) A(t)
    at = days[position]
    lower = int(np.count_nonzero(days < at))
    level = int(np.count_nonzero(days == at)) - 1
    return (lower + 0.5 * level + 0.5) / count
