"""Unit tests for the generalization table (spec P4 section 8.2)."""

import pytest

from pool.artifacts import ManifestError
from providers.fake.generalize import FakeGeneralizer
from tests.unit.test_generator import _fit_config
from validation.generalize import (build_table, ensure_table, table_hash,
                                   vocabulary_digest)

VOCABULARY = ("brass sextant", "sea", "tall tower")


def _clock() -> str:
    return "2026-01-01T00:00:00+00:00"


def test_the_fake_rule_gives_p02_fixed_points() -> None:
    from pool.preparation.stages.normalize import normalize_element

    table, kept = build_table(VOCABULARY, FakeGeneralizer())
    assert table == {"brass sextant": "general sextant",
                     "sea": "general sea",
                     "tall tower": "general tower"}
    assert kept == 0
    for phrase in table.values():
        assert normalize_element(phrase) == phrase


def test_an_emptying_normalization_keeps_the_entry() -> None:
    class _Empties:
        def generalize(self, texts):
            # White space alone normalizes to the empty string.
            return ["   " for _ in texts]

    table, kept = build_table(("sea", "sky"), _Empties())
    assert table == {"sea": "sea", "sky": "sky"}
    assert kept == 2


def test_the_table_is_written_one_time(tmp_path) -> None:
    config = _fit_config()
    first = ensure_table(data_root=tmp_path, vocabulary=VOCABULARY,
                         config=config, clock=_clock,
                         generalizer=FakeGeneralizer())
    class _Refuses:
        def generalize(self, texts):
            raise AssertionError("a warm read must not build")

    second = ensure_table(data_root=tmp_path, vocabulary=VOCABULARY,
                          config=config, clock=_clock,
                          generalizer=_Refuses())
    assert first == second


def test_a_tampered_stored_table_raises_on_read_back(tmp_path) -> None:
    config = _fit_config()
    ensure_table(data_root=tmp_path, vocabulary=VOCABULARY, config=config,
                 clock=_clock, generalizer=FakeGeneralizer())
    table_path = next(tmp_path.rglob("table.jsonl"))
    lines = table_path.read_text(encoding="utf-8").splitlines()
    table_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="do not cover"):
        ensure_table(data_root=tmp_path, vocabulary=VOCABULARY,
                     config=config, clock=_clock,
                     generalizer=FakeGeneralizer())


def test_a_new_vocabulary_forks_the_table_key(tmp_path) -> None:
    config = _fit_config()
    ensure_table(data_root=tmp_path, vocabulary=VOCABULARY, config=config,
                 clock=_clock, generalizer=FakeGeneralizer())
    ensure_table(data_root=tmp_path,
                 vocabulary=VOCABULARY + ("new element",),
                 config=config, clock=_clock,
                 generalizer=FakeGeneralizer())
    assert len(list(tmp_path.rglob("table.jsonl"))) == 2


def test_the_table_hash_reads_the_content() -> None:
    assert table_hash({"a": "b"}) != table_hash({"a": "c"})
    assert vocabulary_digest(("a", "b")) != vocabulary_digest(("a", "c"))