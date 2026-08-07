"""Unit tests for the s05 rule in pool.curation.stages.objectsize."""

import numpy as np

from pool.curation.stages.objectsize import object_decisions


def test_fraction_at_the_limit_gets_rejected() -> None:
    fractions = np.array([0.15], dtype=np.float32)
    result = object_decisions(["a"], fractions, 0.15)
    assert result.survivors == ()
    rejection = result.rejections[0]
    assert rejection.key == "a"
    assert rejection.stage == "s05-object"
    assert rejection.reason == "object-size"
    assert rejection.measured == 0.15


def test_fraction_just_above_the_limit_stays() -> None:
    fractions = np.array([0.150001], dtype=np.float32)
    result = object_decisions(["a"], fractions, 0.15)
    assert result.survivors == ("a",)
    assert result.rejections == ()


def test_zero_fraction_gets_rejected() -> None:
    fractions = np.array([0.0], dtype=np.float32)
    result = object_decisions(["a"], fractions, 0.15)
    assert result.survivors == ()
    assert result.rejections[0].measured == 0.0


def test_measured_value_is_stored_quantized() -> None:
    fractions = np.array([0.0123456789], dtype=np.float32)
    result = object_decisions(["a"], fractions, 0.15)
    assert result.rejections[0].measured == 0.012346


def test_accounting_and_input_sequence() -> None:
    image_ids = ["a", "b", "c"]
    fractions = np.array([0.5, 0.15, 0.2], dtype=np.float32)
    result = object_decisions(image_ids, fractions, 0.15)
    assert result.survivors == ("a", "c")
    assert [r.key for r in result.rejections] == ["b"]
    assert len(result.survivors) + len(result.rejections) == len(image_ids)
