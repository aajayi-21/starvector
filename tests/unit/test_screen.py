"""Unit tests for the s01 screen rules in pool.curation.stages.screen."""

from pool.curation.config import ScreenSection
from pool.curation.stages.screen import screen_decisions
from pool.curation.types import CandidateRecord

_SCREEN = ScreenSection(min_short_side=512, min_aspect=0.5, max_aspect=2.0)


def _candidate(
    source_key: str, width: int | None, height: int | None
) -> CandidateRecord:
    return CandidateRecord(
        source_key=source_key,
        claimed_width=width,
        claimed_height=height,
        captions=(),
        attribution=(),
    )


def test_short_side_at_the_limit_stays() -> None:
    result = screen_decisions([_candidate("a", 512, 512)], _SCREEN)
    assert [c.source_key for c in result.survivors] == ["a"]
    assert result.rejections == ()


def test_short_side_below_the_limit_gets_rejected() -> None:
    result = screen_decisions([_candidate("a", 511, 600)], _SCREEN)
    assert result.survivors == ()
    rejection = result.rejections[0]
    assert rejection.key == "a"
    assert rejection.stage == "s01-screen"
    assert rejection.reason == "resolution-metadata"
    assert rejection.measured == 511.0


def test_aspect_limits_are_inclusive() -> None:
    candidates = [_candidate("low", 512, 1024), _candidate("high", 1024, 512)]
    result = screen_decisions(candidates, _SCREEN)
    assert [c.source_key for c in result.survivors] == ["low", "high"]
    assert result.rejections == ()


def test_aspect_outside_the_range_gets_rejected() -> None:
    candidates = [_candidate("thin", 980, 2000), _candidate("wide", 2050, 1000)]
    result = screen_decisions(candidates, _SCREEN)
    assert result.survivors == ()
    thin, wide = result.rejections
    assert (thin.key, thin.reason, thin.measured) == ("thin", "aspect-metadata", 0.49)
    assert (wide.key, wide.reason, wide.measured) == ("wide", "aspect-metadata", 2.05)


def test_missing_claimed_dimensions_go_through() -> None:
    candidates = [
        _candidate("none", None, None),
        _candidate("width-only", 512, None),
        _candidate("height-only", None, 512),
    ]
    result = screen_decisions(candidates, _SCREEN)
    assert [c.source_key for c in result.survivors] == ["none", "width-only", "height-only"]
    assert result.rejections == ()


def test_r2_wins_when_r2_and_r3_are_broken() -> None:
    result = screen_decisions([_candidate("a", 400, 900)], _SCREEN)
    rejection = result.rejections[0]
    assert rejection.reason == "resolution-metadata"
    assert rejection.measured == 400.0


def test_accounting_and_input_sequence() -> None:
    candidates = [
        _candidate("a", 512, 512),
        _candidate("b", 100, 100),
        _candidate("c", None, None),
        _candidate("d", 3000, 1000),
        _candidate("e", 600, 700),
    ]
    result = screen_decisions(candidates, _SCREEN)
    assert [c.source_key for c in result.survivors] == ["a", "c", "e"]
    assert [r.key for r in result.rejections] == ["b", "d"]
    assert len(result.survivors) + len(result.rejections) == len(candidates)
