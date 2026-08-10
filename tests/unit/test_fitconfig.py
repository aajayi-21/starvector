"""Unit tests for the fit configuration surface (spec P4 §6)."""

import pytest

from pipeline.config import ConfigError
from validation.fitconfig import (fit_config_hash, fit_config_to_json_value,
                                  parse_fit_config)
from tests.unit.test_generator import _FIT_DOCUMENT


def _document(**overrides):
    import copy

    document = copy.deepcopy(_FIT_DOCUMENT)
    for dotted, value in overrides.items():
        node = document
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return document


def test_the_document_round_trips() -> None:
    config = parse_fit_config(_document(), "test")
    assert fit_config_to_json_value(config) == _document()


def test_an_unknown_field_names_its_path() -> None:
    with pytest.raises(ConfigError, match="fit: unknown"):
        parse_fit_config(_document(**{"fit.surprise": 1}), "test")


def test_the_top_level_must_be_the_noise_control() -> None:
    bad = _document()
    bad["generator"]["levels"][-1]["n_atoms"] = 2
    with pytest.raises(ConfigError, match="no-information control"):
        parse_fit_config(bad, "test")


def test_an_openrouter_generalizer_needs_the_placeholder() -> None:
    bad = _document(**{"generalize.provider": "openrouter",
                       "generalize.model": "test/model",
                       "generalize.instruction_template": "broaden this"})
    with pytest.raises(ConfigError, match=r"\{element\}"):
        parse_fit_config(bad, "test")


def test_widths_must_ascend() -> None:
    with pytest.raises(ConfigError, match="strictly ascending"):
        parse_fit_config(
            _document(**{"harness.v6_tier1_widths": [10, 5]}), "test")


def test_each_field_moves_the_hash() -> None:
    base = fit_config_hash(parse_fit_config(_document(), "test"))
    for override in ({"fit.split_salt": "moved"},
                     {"fit.synthetic_seed": 99},
                     {"tag": "dev-moved"},
                     {"generalize.provider": "fake"}):
        moved = fit_config_hash(parse_fit_config(_document(**override),
                                                 "test"))
        if override == {"generalize.provider": "fake"}:
            # The base document is fake — this override is the same
            # document, thus the hash stays.
            assert moved == base
        else:
            assert moved != base, override
