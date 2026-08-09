"""Layer 5 normalization: commonness correction, then standardizing.

Implements docs/ARCHITECTURE.md section 13 through
docs/specs/scoring-path.md section 10. Runs for each channel alone
(R13) — nothing here knows a channel name. Correction changes the
ranking. Standardizing does not (Rule 2).
"""

import numpy as np

from core.types import PoolScores


def _checked_scores(scores: PoolScores, name: str) -> None:
    if scores.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got shape {scores.shape}")
    if scores.dtype != np.float32:
        raise ValueError(f"{name} must be float32, got {scores.dtype}")
    if not np.isfinite(scores).all():
        # NaN clears == and < comparisons without a signal, and a
        # NaN-fed rank is a plausible number that is incorrect (R14).
        raise ValueError(f"{name} holds a non-finite value")


def commonness_correct(raw: PoolScores, commonness: PoolScores) -> PoolScores:
    """Remove each image's baseline appeal (architecture section 13.1).

    corrected = 2 * raw - commonness. raw and commonness are length N.
    """
    _checked_scores(raw, "raw")
    _checked_scores(commonness, "commonness")
    if raw.shape != commonness.shape:
        raise ValueError(
            f"length mismatch: raw {raw.shape} against commonness "
            f"{commonness.shape}")
    corrected = 2.0 * raw.astype(np.float64) - commonness   # (N,)
    return corrected.astype(np.float32)


def standardize(scores: PoolScores) -> PoolScores:
    """Rescale to average 0 and standard deviation 1 across the pool.

    Architecture section 13.3. Population standard deviation (ddof 0),
    accumulated in float64 in a fixed sequence. A deviation of zero
    means the channel gave each image an equal score — degenerate, and
    a silent zero makes plausible numbers that are incorrect (R14) —
    thus it raises.
    """
    _checked_scores(scores, "scores")
    wide = scores.astype(np.float64)
    average = wide.mean()
    deviation = wide.std(ddof=0)
    if deviation == 0.0:
        raise ValueError(
            "standard deviation is zero: the channel gave each image an "
            "equal score")
    return ((wide - average) / deviation).astype(np.float32)   # (N,)
