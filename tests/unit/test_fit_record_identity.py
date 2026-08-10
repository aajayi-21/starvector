"""Unit tests for the fit record keep-or-stop rule (spec P4 §10.2).

A filled verdict survives a re-run with the same identity, and each
lineage field is part of that identity — a review found the guard
covered three fields and kept a stale curve across a generator or
commonness move.
"""

import json

import pytest

from validation.fit import _kept_verdict

_IDENTITY = {
    "scoring_config_hash": "s" * 64,
    "fit_config_hash": "f" * 64,
    "index_id": "i" * 64,
    "union_index_id": "u" * 64,
    "preparation_version_id": "p" * 64,
    "commonness_config_hash": "c" * 64,
    "generator_config_hash": "g" * 64,
}


def _written(tmp_path, content):
    path = tmp_path / "fit-dev-abcd1234.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path


def test_a_pending_verdict_is_replaced(tmp_path) -> None:
    path = _written(tmp_path, {**_IDENTITY, "verdict": "pending"})
    assert _kept_verdict(path, dict(_IDENTITY)) is False


def test_a_filled_verdict_with_the_same_identity_is_kept(tmp_path) -> None:
    path = _written(tmp_path, {**_IDENTITY, "verdict": "pass"})
    assert _kept_verdict(path, dict(_IDENTITY)) is True


@pytest.mark.parametrize("field", sorted(_IDENTITY))
def test_a_moved_identity_field_raises(tmp_path, field) -> None:
    path = _written(tmp_path, {**_IDENTITY, "verdict": "pass"})
    content = {**_IDENTITY, field: "x" * 64}
    with pytest.raises(ValueError, match=field):
        _kept_verdict(path, content)
