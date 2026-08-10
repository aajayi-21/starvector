"""Unit tests for the scoring config loader (spec P2 section 9)."""

import copy

import pytest

from conftest import scoring_config_dict
from pipeline.config import (ConfigError, config_to_json_value,
                             parse_scoring_config, scoring_config_hash)

RECORD = "unused-record.json"


def _base() -> dict:
    return scoring_config_dict(RECORD)


def test_the_document_round_trips() -> None:
    document = _base()
    config = parse_scoring_config(copy.deepcopy(document), "test")
    assert config_to_json_value(config) == document


def test_an_unknown_field_names_its_path() -> None:
    document = _base()
    document["intake"]["extra"] = 1
    with pytest.raises(ConfigError, match=r"test\.intake: unknown"):
        parse_scoring_config(document, "test")


def test_a_missing_field_names_its_path() -> None:
    document = _base()
    del document["validation"]["tag"]
    with pytest.raises(ConfigError, match=r"validation\.tag: missing"):
        parse_scoring_config(document, "test")


def test_a_render_section_is_an_unknown_field_by_construction() -> None:
    document = _base()
    document["render"] = {"canvas_px": 512}
    with pytest.raises(ConfigError, match="unknown field.*render"):
        parse_scoring_config(document, "test")


def test_the_dev_tag_rule_holds_in_the_two_directions() -> None:
    document = _base()
    document["validation"]["tag"] = "live"
    with pytest.raises(ConfigError, match="dev-"):
        parse_scoring_config(document, "test")
    document = _base()
    document["report"]["dev_only"] = False
    with pytest.raises(ConfigError, match="dev-"):
        parse_scoring_config(document, "test")


def test_a_non_finite_number_is_rejected_with_its_path() -> None:
    document = _base()
    document["commonness"]["split_fractions"]["v1"] = float("nan")
    with pytest.raises(ConfigError, match=r"split_fractions\.v1.*finite"):
        parse_scoring_config(document, "test")
    document = _base()
    document["fusion"]["weights"]["outline"] = float("inf")
    with pytest.raises(ConfigError, match=r"weights\.outline.*finite"):
        parse_scoring_config(document, "test")


def test_a_zero_weight_is_rejected_as_deactivation() -> None:
    document = _base()
    document["fusion"]["weights"]["outline"] = 0.0
    with pytest.raises(ConfigError, match="deactivation"):
        parse_scoring_config(document, "test")


def test_an_unbuilt_channel_in_the_weights_is_rejected() -> None:
    document = _base()
    document["fusion"]["weights"]["placement"] = 1.0
    with pytest.raises(ConfigError, match="not a built channel"):
        parse_scoring_config(document, "test")


def test_the_element_channel_is_built_and_weighted() -> None:
    config = parse_scoring_config(_base(), "test")
    assert dict(config.fusion.weights) == {"outline": 1.0, "element": 1.0}
    assert config.channels.element.matching_rule == "sinkhorn-slack-v1"


def test_an_alpha_below_one_is_rejected() -> None:
    document = _base()
    document["channels"]["element"]["alpha"] = 0.5
    with pytest.raises(ConfigError, match="not built"):
        parse_scoring_config(document, "test")


def test_an_unknown_submission_mode_is_rejected() -> None:
    document = _base()
    document["validation"]["submission_mode"] = "drawing"
    with pytest.raises(ConfigError, match="expected one of"):
        parse_scoring_config(document, "test")


def test_split_fractions_above_one_are_rejected() -> None:
    document = _base()
    document["commonness"]["split_fractions"]["background"] = 0.9
    with pytest.raises(ConfigError, match="sum above 1.0"):
        parse_scoring_config(document, "test")


def test_the_dataset_cross_field_rules_hold() -> None:
    document = _base()
    document["commonness"]["dataset"]["url"] = "https://example.org/a.tar.gz"
    with pytest.raises(ConfigError, match="must be null for the fake"):
        parse_scoring_config(document, "test")
    document = _base()
    document["commonness"]["dataset"]["provider"] = "fscoco"
    with pytest.raises(ConfigError, match="url: required"):
        parse_scoring_config(document, "test")


def test_the_hash_is_stable_and_ignores_runtime() -> None:
    config = parse_scoring_config(_base(), "test")
    hashes = {"sketch_encoder": "a" * 64, "sketch_pairs": "b" * 64,
              "text_encoder": "c" * 64}
    first = scoring_config_hash(config, hashes)
    assert first == scoring_config_hash(config, hashes)
    moved = parse_scoring_config(
        scoring_config_dict(RECORD, **{"runtime.device": "cuda"}), "test")
    assert scoring_config_hash(moved, hashes) == first
    gated = parse_scoring_config(
        scoring_config_dict(RECORD, **{"intake.min_ink_pixels": 5}), "test")
    assert scoring_config_hash(gated, hashes) != first


def test_the_hash_needs_exactly_the_three_slot_names() -> None:
    config = parse_scoring_config(_base(), "test")
    with pytest.raises(ValueError, match="text_encoder"):
        scoring_config_hash(config, {"sketch_encoder": "a" * 64,
                                     "sketch_pairs": "b" * 64})
