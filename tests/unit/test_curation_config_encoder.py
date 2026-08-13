"""Unit: the curation encoder slot after the U2 change.

An openrouter embedding encoder parses with a required model and
dimension. The chat-slot instruction rule stays, the fake encoder
stays for tests, and no other provider clears the gate.
"""

import pytest

from conftest import base_config_dict, make_config
from pool.curation.config import (ConfigError, curation_config_hash,
                                  parse_curation_config)

OPENROUTER_ENCODER = {
    "provider": "openrouter", "model": "google/gemini-embedding-2",
    "instruction_template": None, "dimension": 3072,
    "probability_sum_tolerance": None,
}


def test_an_openrouter_encoder_parses_with_model_and_dimension() -> None:
    config = make_config(**{"providers.encoder": dict(OPENROUTER_ENCODER)})
    assert config.providers.encoder.provider == "openrouter"
    assert config.providers.encoder.model == "google/gemini-embedding-2"
    assert config.providers.encoder.dimension == 3072
    assert config.providers.encoder.instruction_template is None


def test_the_openrouter_encoder_requires_a_model() -> None:
    # The chat default_model must not leak into an embeddings slot.
    slot = dict(OPENROUTER_ENCODER)
    slot["model"] = None
    with pytest.raises(ConfigError, match="encoder.model"):
        make_config(**{"providers.encoder": slot})


def test_the_encoder_requires_a_dimension_with_each_provider() -> None:
    for provider in ("openrouter", "fake"):
        slot = dict(OPENROUTER_ENCODER)
        slot["provider"] = provider
        slot["dimension"] = None
        with pytest.raises(ConfigError, match="encoder.dimension"):
            make_config(**{"providers.encoder": slot})


def test_the_chat_slot_instruction_rule_stays() -> None:
    slot = {
        "provider": "openrouter", "model": None,
        "instruction_template": None, "dimension": None,
        "probability_sum_tolerance": None,
    }
    with pytest.raises(ConfigError, match="instruction_template"):
        make_config(**{"providers.classifier": slot})


def test_a_local_encoder_is_still_rejected() -> None:
    slot = dict(OPENROUTER_ENCODER)
    slot["provider"] = "local"
    with pytest.raises(ConfigError, match="provider"):
        make_config(**{"providers.encoder": slot})


def test_the_encoder_model_and_dimension_move_the_config_hash() -> None:
    hashes = {name: "a" * 64
              for name in ("corpus", "text_coverage", "classifier",
                           "object_size", "encoder")}
    base = curation_config_hash(
        make_config(**{"providers.encoder": dict(OPENROUTER_ENCODER)}),
        hashes)
    moved_model = dict(OPENROUTER_ENCODER)
    moved_model["model"] = "google/gemini-embedding-3"
    moved_dimension = dict(OPENROUTER_ENCODER)
    moved_dimension["dimension"] = 1536
    assert curation_config_hash(
        make_config(**{"providers.encoder": moved_model}), hashes) != base
    assert curation_config_hash(
        make_config(**{"providers.encoder": moved_dimension}),
        hashes) != base


def test_input_canvas_px_parses_on_the_encoder_alone() -> None:
    slot = dict(OPENROUTER_ENCODER)
    slot["input_canvas_px"] = 512
    config = make_config(**{"providers.encoder": slot})
    assert config.providers.encoder.input_canvas_px == 512
    chat = {
        "provider": "fake", "model": None, "instruction_template": None,
        "dimension": None, "probability_sum_tolerance": None,
        "input_canvas_px": 512,
    }
    with pytest.raises(ConfigError, match="input_canvas_px"):
        make_config(**{"providers.classifier": chat})


def test_input_canvas_px_is_absent_from_the_document_at_none() -> None:
    # The omission rule: a config released before the field keeps
    # its document and thus its hash.
    from pool.curation.config import config_to_json_value

    base = make_config()
    assert base.providers.encoder.input_canvas_px is None
    document = config_to_json_value(base)
    assert "input_canvas_px" not in document["providers"]["encoder"]
    hashes = {name: "a" * 64
              for name in ("corpus", "text_coverage", "classifier",
                           "object_size", "encoder")}
    slot = dict(OPENROUTER_ENCODER)
    plain = curation_config_hash(
        make_config(**{"providers.encoder": slot}), hashes)
    sized = dict(OPENROUTER_ENCODER)
    sized["input_canvas_px"] = 512
    moved = curation_config_hash(
        make_config(**{"providers.encoder": sized}), hashes)
    assert moved != plain
