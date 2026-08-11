"""Unit tests for the V3 verdict rules (spec P4 §11, R4)."""

from validation.v3 import V3Level, monotone_verdict


def _level(level: int, mean_p: float, low: float, high: float) -> V3Level:
    return V3Level(level=level, trial_count=10, mean_p=mean_p, low=low,
                   high=high)


def test_the_verdict_reads_the_quantized_means() -> None:
    # The two means are closer than the record's six-digit rounding:
    # the recorded numbers are equal, thus the verdict must not claim
    # a sequence the record cannot show (ruling 2026-08-10).
    levels = [_level(0, 0.9000000004, 0.85, 0.95),
              _level(1, 0.9000000001, 0.85, 0.95),
              _level(2, 0.5, 0.45, 0.55)]
    ordered, _ = monotone_verdict(levels)
    assert ordered is False


def test_a_descending_curve_with_the_control_at_half_clears() -> None:
    levels = [_level(0, 0.9, 0.85, 0.95),
              _level(1, 0.7, 0.65, 0.75),
              _level(2, 0.5, 0.45, 0.55)]
    ordered, control = monotone_verdict(levels)
    assert ordered is True and control is True


def test_a_control_away_from_half_fails() -> None:
    levels = [_level(0, 0.9, 0.85, 0.95),
              _level(1, 0.62, 0.56, 0.68)]
    _, control = monotone_verdict(levels)
    assert control is False
