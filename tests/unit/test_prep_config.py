"""Unit tests for the preparation config: strict parsing and the hash."""

import copy
import json

import pytest

from pool.preparation.config import (
    SLOT_NAMES,
    ConfigError,
    config_to_json_value,
    load_preparation_config,
    parse_preparation_config,
    preparation_config_hash,
)


def _base_raw() -> dict:
    return {
        "config_version": 1,
        "input": {"release_record": "pool/releases/dev-wit-001-b89d8614.json"},
        "elements": {
            "counts": {
                "objects": 3,
                "materials": 3,
                "colors": 3,
                "shapes": 2,
                "scale": 1,
                "setting": 1,
                "ambience": 3,
            },
            "max_elements": 20,
            "normalize_rule": "d7-v1",
        },
        "linedraw": {
            "binarize_threshold": 0.5,
            "min_segment_px": 10,
            "canvas_px": 512,
            "line_width_px": 3,
            "background": "white",
            "antialias": False,
        },
        "outline": {"crop_fraction": 0.6, "crop_grid": "center-corners"},
        "neardup": {"similarity_threshold": 0.95},
        "providers": {
            "openrouter": {
                "default_model": "openai/gpt-5.6-luna",
                "max_concurrency": 4,
                "requests_per_second": 2.0,
                "timeout_seconds": 60.0,
                "retry_limit": 3,
                "response_format_mode": "json_schema",
            },
            "describer": {
                "provider": "fake",
                "model": None,
                "instruction_template": None,
                "dimension": None,
            },
            "text_encoder": {
                "provider": "fake",
                "model": None,
                "instruction_template": None,
                "dimension": 64,
            },
            "image_encoder": {
                "provider": "fake",
                "model": None,
                "instruction_template": None,
                "dimension": 64,
            },
            "line_drawer": {
                "provider": "fake",
                "model": None,
                "instruction_template": None,
                "dimension": None,
            },
            "element_boxes": {
                "provider": "fake",
                "model": None,
                "instruction_template": None,
                "dimension": None,
            },
        },
        "runtime": {"device": "auto"},
        "release": {"tag": "dev-prep-001", "dev_only": True},
    }


def _hashes() -> dict[str, str]:
    return {slot: f"hash-{slot}" for slot in SLOT_NAMES}


def test_base_config_parses() -> None:
    config = parse_preparation_config(_base_raw())
    assert config.elements.max_elements == 20
    assert config.elements.counts.shapes == 2
    assert config.outline.crop_fraction == 0.6
    assert config.providers.text_encoder.dimension == 64
    assert config.release.dev_only is True


def test_round_trip_is_identity() -> None:
    raw = _base_raw()
    assert config_to_json_value(parse_preparation_config(raw)) == raw


def test_unknown_field_names_path() -> None:
    raw = _base_raw()
    raw["outline"]["surprise"] = 1
    with pytest.raises(ConfigError, match=r"config\.outline: unknown field\(s\): surprise"):
        parse_preparation_config(raw)


def test_unknown_top_level_field() -> None:
    raw = _base_raw()
    raw["extra_section"] = {}
    with pytest.raises(ConfigError, match="unknown field"):
        parse_preparation_config(raw)


def test_missing_field_names_path() -> None:
    raw = _base_raw()
    del raw["elements"]["max_elements"]
    with pytest.raises(ConfigError, match=r"config\.elements\.max_elements: missing field"):
        parse_preparation_config(raw)


def test_counts_must_be_positive() -> None:
    raw = _base_raw()
    raw["elements"]["counts"]["objects"] = 0
    with pytest.raises(ConfigError, match=r"counts\.objects"):
        parse_preparation_config(raw)


def test_normalize_rule_is_pinned() -> None:
    raw = _base_raw()
    raw["elements"]["normalize_rule"] = "d7-v2"
    with pytest.raises(ConfigError, match="normalize_rule"):
        parse_preparation_config(raw)


def test_background_choice() -> None:
    raw = _base_raw()
    raw["linedraw"]["background"] = "black"
    with pytest.raises(ConfigError, match="background"):
        parse_preparation_config(raw)


def test_crop_fraction_zero_is_out_of_range() -> None:
    raw = _base_raw()
    raw["outline"]["crop_fraction"] = 0.0
    with pytest.raises(ConfigError, match="crop_fraction"):
        parse_preparation_config(raw)


def test_similarity_threshold_above_one_is_out_of_range() -> None:
    raw = _base_raw()
    raw["neardup"]["similarity_threshold"] = 1.5
    with pytest.raises(ConfigError, match="similarity_threshold"):
        parse_preparation_config(raw)


def test_describer_rejects_local_provider() -> None:
    raw = _base_raw()
    raw["providers"]["describer"]["provider"] = "local"
    with pytest.raises(ConfigError, match=r"providers\.describer\.provider"):
        parse_preparation_config(raw)


def test_line_drawer_rejects_openrouter_provider() -> None:
    raw = _base_raw()
    raw["providers"]["line_drawer"]["provider"] = "openrouter"
    with pytest.raises(ConfigError, match=r"providers\.line_drawer\.provider"):
        parse_preparation_config(raw)


def test_openrouter_describer_requires_template() -> None:
    raw = _base_raw()
    raw["providers"]["describer"]["provider"] = "openrouter"
    with pytest.raises(ConfigError, match=r"providers\.describer\.instruction_template"):
        parse_preparation_config(raw)


def test_openrouter_element_boxes_requires_template() -> None:
    raw = _base_raw()
    raw["providers"]["element_boxes"]["provider"] = "openrouter"
    with pytest.raises(ConfigError, match=r"providers\.element_boxes\.instruction_template"):
        parse_preparation_config(raw)


def test_fake_text_encoder_requires_dimension() -> None:
    raw = _base_raw()
    raw["providers"]["text_encoder"]["dimension"] = None
    with pytest.raises(ConfigError, match=r"providers\.text_encoder\.dimension"):
        parse_preparation_config(raw)


def test_openrouter_image_encoder_requires_dimension() -> None:
    raw = _base_raw()
    raw["providers"]["image_encoder"]["provider"] = "openrouter"
    raw["providers"]["image_encoder"]["model"] = "google/gemini-embedding-2"
    raw["providers"]["image_encoder"]["dimension"] = None
    with pytest.raises(ConfigError, match=r"providers\.image_encoder\.dimension"):
        parse_preparation_config(raw)


def test_openrouter_text_encoder_requires_model() -> None:
    raw = _base_raw()
    raw["providers"]["text_encoder"]["provider"] = "openrouter"
    with pytest.raises(ConfigError, match=r"providers\.text_encoder\.model"):
        parse_preparation_config(raw)


def test_local_encoder_requires_model() -> None:
    raw = _base_raw()
    raw["providers"]["image_encoder"]["provider"] = "local"
    with pytest.raises(ConfigError, match=r"providers\.image_encoder\.model"):
        parse_preparation_config(raw)


def test_local_line_drawer_requires_model() -> None:
    raw = _base_raw()
    raw["providers"]["line_drawer"]["provider"] = "local"
    with pytest.raises(ConfigError, match=r"providers\.line_drawer\.model"):
        parse_preparation_config(raw)


def test_dev_only_requires_dev_tag() -> None:
    raw = _base_raw()
    raw["release"]["tag"] = "prep-001"
    with pytest.raises(ConfigError, match=r"release\.tag"):
        parse_preparation_config(raw)


def test_dev_tag_requires_dev_only() -> None:
    raw = _base_raw()
    raw["release"]["dev_only"] = False
    with pytest.raises(ConfigError, match=r"release\.tag"):
        parse_preparation_config(raw)


def test_hash_requires_the_five_slot_keys() -> None:
    config = parse_preparation_config(_base_raw())
    hashes = _hashes()
    del hashes["line_drawer"]
    with pytest.raises(ValueError, match="provider_config_hashes"):
        preparation_config_hash(config, hashes)
    hashes["line_drawer"] = "x"
    hashes["corpus"] = "y"
    with pytest.raises(ValueError, match="provider_config_hashes"):
        preparation_config_hash(config, hashes)


def test_hash_moves_on_one_value_change() -> None:
    base = parse_preparation_config(_base_raw())
    changed_raw = _base_raw()
    changed_raw["neardup"]["similarity_threshold"] = 0.9
    changed = parse_preparation_config(changed_raw)
    assert preparation_config_hash(base, _hashes()) != preparation_config_hash(
        changed, _hashes()
    )


def test_hash_moves_on_provider_hash_change() -> None:
    config = parse_preparation_config(_base_raw())
    moved = _hashes()
    moved["describer"] = "another"
    assert preparation_config_hash(config, _hashes()) != preparation_config_hash(config, moved)


def test_hash_is_stable() -> None:
    config = parse_preparation_config(_base_raw())
    again = parse_preparation_config(copy.deepcopy(_base_raw()))
    assert preparation_config_hash(config, _hashes()) == preparation_config_hash(
        again, _hashes()
    )


def test_load_reads_a_file(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(_base_raw()), encoding="utf-8")
    config = load_preparation_config(path)
    assert config.linedraw.canvas_px == 512


def test_load_bad_json_is_a_config_error(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot read config"):
        load_preparation_config(path)


def test_runtime_device_choice_is_validated() -> None:
    raw = _base_raw()
    raw["runtime"]["device"] = "tpu"
    with pytest.raises(ConfigError, match="runtime.device"):
        parse_preparation_config(raw)


def test_runtime_device_does_not_move_the_hash() -> None:
    # The device is machine-local. The same pipeline config on a CUDA
    # machine and an XPU machine must address the same artifact tree.
    hashes = {}
    for device in ("auto", "cuda", "xpu", "cpu"):
        raw = _base_raw()
        raw["runtime"]["device"] = device
        hashes[device] = preparation_config_hash(parse_preparation_config(raw), _hashes())
    assert len(set(hashes.values())) == 1


def test_runtime_section_is_required() -> None:
    raw = _base_raw()
    del raw["runtime"]
    with pytest.raises(ConfigError, match="runtime"):
        parse_preparation_config(raw)


def test_detect_resolution_absent_and_null_agree() -> None:
    hashes = {name: "a" * 64 for name in SLOT_NAMES}
    absent = parse_preparation_config(_base_raw())
    raw = _base_raw()
    raw["linedraw"]["detect_resolution_px"] = None
    explicit_null = parse_preparation_config(raw)
    assert absent.linedraw.detect_resolution_px is None
    assert explicit_null.linedraw.detect_resolution_px is None
    assert preparation_config_hash(absent, hashes) \
        == preparation_config_hash(explicit_null, hashes)


def test_detect_resolution_stays_out_of_the_document_at_none() -> None:
    # The P2b R5 rule: a config released before the field keeps its
    # document byte-for-byte, thus its hash and its record.
    config = parse_preparation_config(_base_raw())
    assert "detect_resolution_px" not in config_to_json_value(config)["linedraw"]


def test_detect_resolution_value_moves_the_hash() -> None:
    hashes = {name: "a" * 64 for name in SLOT_NAMES}
    base = parse_preparation_config(_base_raw())
    raw = _base_raw()
    raw["linedraw"]["detect_resolution_px"] = 768
    moved = parse_preparation_config(raw)
    assert moved.linedraw.detect_resolution_px == 768
    assert preparation_config_hash(moved, hashes) \
        != preparation_config_hash(base, hashes)
    assert config_to_json_value(moved)["linedraw"]["detect_resolution_px"] == 768


def test_detect_resolution_below_the_minimum_raises() -> None:
    raw = _base_raw()
    raw["linedraw"]["detect_resolution_px"] = 32
    with pytest.raises(ConfigError, match=r"detect_resolution_px"):
        parse_preparation_config(raw)

def test_stroke_color_absent_null_and_mono_agree() -> None:
    # The spec C1 omission rule: a config released before the field
    # keeps its document and thus its hash.
    hashes = {name: "a" * 64 for name in SLOT_NAMES}
    absent = parse_preparation_config(_base_raw())
    raw = _base_raw()
    raw["linedraw"]["stroke_color"] = "mono"
    explicit = parse_preparation_config(raw)
    assert absent.linedraw.stroke_color == "mono"
    assert explicit.linedraw.stroke_color == "mono"
    assert preparation_config_hash(absent, hashes) \
        == preparation_config_hash(explicit, hashes)
    assert "stroke_color" not in config_to_json_value(absent)["linedraw"]


def test_stroke_color_rgb_moves_the_hash() -> None:
    hashes = {name: "a" * 64 for name in SLOT_NAMES}
    base = parse_preparation_config(_base_raw())
    raw = _base_raw()
    raw["linedraw"]["stroke_color"] = "rgb"
    moved = parse_preparation_config(raw)
    assert moved.linedraw.stroke_color == "rgb"
    assert preparation_config_hash(moved, hashes) \
        != preparation_config_hash(base, hashes)
    assert config_to_json_value(moved)["linedraw"]["stroke_color"] == "rgb"


def test_a_bad_stroke_color_names_the_path() -> None:
    raw = _base_raw()
    raw["linedraw"]["stroke_color"] = "sepia"
    with pytest.raises(ConfigError, match="stroke_color"):
        parse_preparation_config(raw)
