"""The Voyage slots wire a Voyage encoder, and no slot falls to a fake.

Spec: docs/specs/voyage-encoder.md section 4. These tests run offline:
a wired encoder posts nothing until its first encode.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from pipeline.config import ConfigError, load_scoring_config, parse_scoring_config
from pool.preparation.config import load_preparation_config, parse_preparation_config
from pool.preparation.run import _slot_hash, wire_slot
from providers.voyage.embeddings import (VoyageImageEncoder, VoyageSlotConfig,
                                         VoyageTextEncoder, voyage_config_hash)
from validation import harness

SCORING = Path("configs/scoring/dev-wit-photo-inst-sym-3.json")
PREPARATION = Path("configs/preparation/dev-wit-photo-inst-2.json")
MODEL = "voyage-multimodal-3.5"


def voyage_scoring() -> dict:
    raw = json.loads(SCORING.read_text())
    raw["providers"]["sketch_encoder"].update(
        provider="voyage", model=MODEL, dimension=1024)
    raw["providers"]["text_encoder"].update(
        provider="voyage", model=MODEL, dimension=1024)
    return raw


def voyage_preparation() -> dict:
    raw = json.loads(PREPARATION.read_text())
    raw["providers"]["image_encoder"].update(
        provider="voyage", model=MODEL, dimension=1024)
    raw["providers"]["text_encoder"].update(
        provider="voyage", model=MODEL, dimension=1024)
    return raw


@pytest.fixture
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "test-key")


def test_the_scoring_slots_wire_voyage_encoders(key: None, tmp_path: Path) -> None:
    config = parse_scoring_config(voyage_scoring())
    sketch = harness.wire_sketch_encoder(config, tmp_path)
    text = harness.wire_text_encoder(config, tmp_path)
    assert isinstance(sketch, VoyageImageEncoder)
    assert isinstance(text, VoyageTextEncoder)
    assert sketch.config_hash == harness.sketch_encoder_hash(config)
    assert text.config_hash == harness.text_encoder_hash(config)


def test_the_preparation_slots_wire_voyage_encoders(key: None, tmp_path: Path) -> None:
    config = parse_preparation_config(voyage_preparation())
    image = wire_slot("image_encoder", config, tmp_path)
    text = wire_slot("text_encoder", config, tmp_path)
    assert isinstance(image, VoyageImageEncoder)
    assert isinstance(text, VoyageTextEncoder)
    slot = config.providers.image_encoder
    assert image.config_hash == _slot_hash("image_encoder", slot, config)
    assert image.config_hash == voyage_config_hash(VoyageSlotConfig(
        "image_encoder", MODEL, 1024, slot.instruction_template))


@pytest.mark.parametrize("slot", ["sketch_encoder", "text_encoder"])
def test_an_unknown_provider_raises_and_wires_no_fake(slot: str, tmp_path: Path) -> None:
    config = parse_scoring_config(voyage_scoring())
    section = getattr(config.providers, slot)
    broken = dataclasses.replace(
        config,
        providers=dataclasses.replace(
            config.providers,
            **{slot: dataclasses.replace(section, provider="tomorrow")}),
    )
    wire = (harness.wire_sketch_encoder if slot == "sketch_encoder"
            else harness.wire_text_encoder)
    hash_of = (harness.sketch_encoder_hash if slot == "sketch_encoder"
               else harness.text_encoder_hash)
    with pytest.raises(ValueError, match="unknown"):
        wire(broken, tmp_path)
    with pytest.raises(ValueError, match="unknown"):
        hash_of(broken)


@pytest.mark.parametrize("slot", ["sketch_encoder", "text_encoder"])
def test_a_voyage_scoring_slot_needs_its_model(slot: str) -> None:
    raw = voyage_scoring()
    raw["providers"][slot]["model"] = None
    with pytest.raises(ConfigError, match="model"):
        parse_scoring_config(raw)


def test_a_sketch_slot_on_a_different_provider_is_refused() -> None:
    gemini_pool = load_preparation_config(PREPARATION)
    voyage_sketches = parse_scoring_config(voyage_scoring())
    with pytest.raises(ValueError, match="R7"):
        harness.check_outline_space(voyage_sketches, gemini_pool)


def test_a_provider_mismatch_at_one_dimension_is_refused() -> None:
    raw = voyage_scoring()
    raw["providers"]["sketch_encoder"]["dimension"] = 3072
    with pytest.raises(ValueError, match="provider"):
        harness.check_outline_space(parse_scoring_config(raw),
                                    load_preparation_config(PREPARATION))


def test_a_different_voyage_model_is_refused() -> None:
    raw = voyage_scoring()
    raw["providers"]["sketch_encoder"]["model"] = "voyage-multimodal-3"
    pool = parse_preparation_config(voyage_preparation())
    with pytest.raises(ValueError, match="model"):
        harness.check_outline_space(parse_scoring_config(raw), pool)


def test_the_matching_voyage_slots_clear_the_check() -> None:
    harness.check_outline_space(parse_scoring_config(voyage_scoring()),
                                parse_preparation_config(voyage_preparation()))


def test_the_committed_gemini_lineage_keeps_its_hashes() -> None:
    """The stored days rescore through these hashes (I4)."""
    record = json.loads(Path(
        "pool/preparations/dev-wit-prep-photo-inst-2-40f06be1.json").read_text())
    config = load_preparation_config(PREPARATION)
    hashes = record["provider_config_hashes"]
    for slot in ("text_encoder", "image_encoder"):
        assert _slot_hash(slot, getattr(config.providers, slot), config) == hashes[slot]
    scoring = load_scoring_config(SCORING)
    assert harness.text_encoder_hash(scoring) == hashes["text_encoder"]
    harness.check_outline_space(scoring, config)
