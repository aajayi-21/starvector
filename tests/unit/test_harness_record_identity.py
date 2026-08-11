"""Unit tests for the harness keep-or-stop rule (spec P4 §17a).

A filled verdict survives a re-run with the same identity — and the
identity covers the full lineage. The verification run found a
moved generalization table kept a stale verdicted record silently,
because the guard compared three fields.
"""

import json

import pytest

from validation.harness import write_harness_record

_IDENTITY = {
    "index_id": "i" * 64,
    "preparation_version_id": "p" * 64,
    "scoring_config_hash": "s" * 64,
    "fit_config_hash": "f" * 64,
    "commonness_config_hash": "c" * 64,
    "generator_config_hash": "g" * 64,
    "synthetic_seed": 11,
    "synthetic_count": 24,
}


def _write(tmp_path, content):
    return write_harness_record(tmp_path, "v6", "dev", "a" * 64, content)


def _fill_verdict(path):
    record = json.loads(path.read_text(encoding="utf-8"))
    record["verdict"] = "pass"
    path.write_text(json.dumps(record), encoding="utf-8")


def test_a_filled_verdict_with_the_same_identity_is_kept(tmp_path) -> None:
    content = {**_IDENTITY, "verdict": "pending", "value": 1}
    path = _write(tmp_path, content)
    _fill_verdict(path)
    again = _write(tmp_path, {**_IDENTITY, "verdict": "pending", "value": 2})
    assert again == path
    kept = json.loads(path.read_text(encoding="utf-8"))
    assert kept["verdict"] == "pass" and kept["value"] == 1


@pytest.mark.parametrize("field,moved", [
    ("generator_config_hash", "x" * 64),
    ("commonness_config_hash", "x" * 64),
    ("fit_config_hash", "x" * 64),
    ("synthetic_seed", 99),
])
def test_a_moved_lineage_field_raises(tmp_path, field, moved) -> None:
    path = _write(tmp_path, {**_IDENTITY, "verdict": "pending"})
    _fill_verdict(path)
    with pytest.raises(ValueError, match=field):
        _write(tmp_path, {**_IDENTITY, field: moved, "verdict": "pending"})


def test_a_field_the_content_does_not_carry_is_not_compared(
        tmp_path) -> None:
    # A P3-era record shape has no generator identity: a rerun
    # with none in its content keeps the verdict, as before.
    slim = {name: _IDENTITY[name]
            for name in ("index_id", "preparation_version_id",
                         "scoring_config_hash")}
    path = _write(tmp_path, {**slim, "verdict": "pending"})
    _fill_verdict(path)
    assert _write(tmp_path, {**slim, "verdict": "pending"}) == path
