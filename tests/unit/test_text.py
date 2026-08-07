"""Unit tests for the s03 text rule in pool.curation.stages.text."""

import numpy as np

from pool.curation.stages.text import text_decisions


def test_coverage_at_the_limit_stays() -> None:
    coverage = np.array([0.05], dtype=np.float32)
    result = text_decisions(["a"], coverage, 0.05)
    assert result.survivors == ("a",)
    assert result.rejections == ()


def test_coverage_above_the_limit_gets_rejected() -> None:
    coverage = np.array([0.050001], dtype=np.float32)
    result = text_decisions(["a"], coverage, 0.05)
    assert result.survivors == ()
    rejection = result.rejections[0]
    assert rejection.key == "a"
    assert rejection.stage == "s03-text"
    assert rejection.reason == "text-coverage"
    assert rejection.measured == 0.050001


def test_measured_value_is_stored_quantized() -> None:
    coverage = np.array([0.123456789], dtype=np.float32)
    result = text_decisions(["a"], coverage, 0.05)
    assert result.rejections[0].measured == 0.123457


def test_accounting_and_input_sequence() -> None:
    image_ids = ["a", "b", "c", "d"]
    coverage = np.array([0.0, 0.2, 0.05, 0.9], dtype=np.float32)
    result = text_decisions(image_ids, coverage, 0.05)
    assert result.survivors == ("a", "c")
    assert [r.key for r in result.rejections] == ["b", "d"]
    assert len(result.survivors) + len(result.rejections) == len(image_ids)
