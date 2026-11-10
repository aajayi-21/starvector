"""Integration: the fake corpus through the screener and the person rule."""

from pathlib import Path

import pytest
from conftest import make_config, read_stage_jsonl, run_pipeline

from pool.curation.config import ConfigError
from pool.curation.run import _slot_hash

SCREENER_SLOT = {"provider": "screener", "model": None, "instruction_template": None,
                 "dimension": None, "probability_sum_tolerance": None}
SCREENED = {
    "providers.text_coverage": SCREENER_SLOT,
    "providers.classifier": SCREENER_SLOT,
    "providers.object_size": SCREENER_SLOT,
    "providers.screener": {"provider": "fake", "model": None,
                           "instruction_template": None, "input_canvas_px": None},
}
POPULATION = (("photo", 30), ("person_main", 6), ("small_object", 4),
              ("text_heavy", 3), ("diagram", 3))


def rejections(data_root: Path, stage: str) -> dict[str, int]:
    tally: dict[str, int] = {}
    for row in read_stage_jsonl(data_root, stage, "rejections.jsonl"):
        tally[row["reason"]] = tally.get(row["reason"], 0) + 1
    return tally


def test_the_person_rule_rejects_with_its_own_reason(
        tmp_path: Path) -> None:
    config = make_config(**SCREENED, person={"reject_role": "main_subject"})
    run_pipeline(config, tmp_path / "data", tmp_path / "releases",
                 population=POPULATION, through="s05-object")
    tally = rejections(tmp_path / "data", "s05-object")
    assert tally == {"object-size": 4, "person-focus": 6}
    assert rejections(tmp_path / "data", "s03-text") == {"text-coverage": 3}
    assert rejections(tmp_path / "data", "s04-class") == {"class-diagram": 3}


def test_no_person_section_keeps_people(tmp_path: Path) -> None:
    run_pipeline(make_config(**SCREENED), tmp_path / "data", tmp_path / "releases",
                 population=POPULATION, through="s05-object")
    assert rejections(tmp_path / "data", "s05-object") == {"object-size": 4}


def test_the_three_slots_share_one_hash() -> None:
    config = make_config(**SCREENED)
    hashes = {_slot_hash(name, getattr(config.providers, name), config)
              for name in ("text_coverage", "classifier", "object_size")}
    assert len(hashes) == 1


def test_a_screener_slot_with_no_section_is_refused() -> None:
    with pytest.raises(ConfigError, match="screener"):
        make_config(**{"providers.text_coverage": SCREENER_SLOT})


def test_a_section_with_a_separate_slot_is_refused() -> None:
    with pytest.raises(ConfigError, match="screen slots"):
        make_config(**{"providers.text_coverage": SCREENER_SLOT,
                       "providers.screener": SCREENED["providers.screener"]})


def test_an_openrouter_screener_needs_its_instruction() -> None:
    section = {**SCREENED["providers.screener"], "provider": "openrouter"}
    with pytest.raises(ConfigError, match="instruction_template"):
        make_config(**{**SCREENED, "providers.screener": section})


def test_the_committed_curation_hash_does_not_move(monkeypatch) -> None:
    """A stored tree stays addressable with the new optional sections.

    The corpus adapter resolves its revision through the hub, and the
    suite runs with no network. The config pins a full commit hash, and
    the hub resolves a commit hash to itself, thus the test gives that
    value directly. The release record holds the same commit.
    """
    import json

    from pool.curation.config import (curation_config_hash,
                                      load_curation_config)
    from pool.curation.run import provider_config_hashes, wire_corpus
    from providers.corpora.huggingface import HuggingFaceCorpus

    config = load_curation_config(Path("configs/curation/dev-wit-2.json"))
    record = json.loads(
        Path("pool/releases/dev-wit-002-9644fac1.json").read_text())
    assert len(config.corpus.revision) == 40
    assert config.corpus.revision == record["corpus_identity"]["revision"]
    monkeypatch.setattr(HuggingFaceCorpus, "_resolve_revision",
                        lambda self: config.corpus.revision)
    monkeypatch.setattr(HuggingFaceCorpus, "_install_metered_client",
                        lambda self: None)
    hashes = provider_config_hashes(config, wire_corpus(config))
    assert curation_config_hash(config, hashes) == record["curation_config_hash"]
