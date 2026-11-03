"""The production config writer, the prune plan, and the screener check."""

import json
from pathlib import Path

import numpy as np
import pytest
from conftest import make_config

from pipeline.config import parse_scoring_config
from pool.curation.config import parse_curation_config
from pool.preparation.config import parse_preparation_config
from tools import production_configs as writer
from tools.prune_candidates import prune_plan
from validation import harness, screener_check
from validation.fitconfig import load_fit_config

ROOT = Path(".")


def rulings(**overrides: object) -> writer.Rulings:
    values: dict = {"encoder": "voyage", "cell": "inst", "curation_threshold": 0.97,
                    "preparation_threshold": 0.96, "boxes": "deferred",
                    "materialize_cap": 38_000}
    values.update(overrides)
    return writer.Rulings(**values)


@pytest.fixture
def production_release(tmp_path: Path) -> str:
    """A release record with the production shape: no dev flag."""
    record = json.loads(Path("pool/releases/dev-wit-002-9644fac1.json").read_text())
    record["dev_only"] = False
    record["label"] = "prod-wit-001-9644fac1"
    path = tmp_path / "prod-wit-001-9644fac1.json"
    path.write_text(json.dumps(record))
    return str(path)


@pytest.mark.parametrize("encoder", ["voyage", "gemini"])
def test_the_curation_documents_parse_and_hold_the_rulings(encoder: str) -> None:
    documents = writer.curation_documents(rulings(encoder=encoder))
    production = parse_curation_config(documents["curation/prod-wit.json"])
    calibration = parse_curation_config(documents["curation/dev-wit-3.json"])
    assert production.release.tag == "prod-wit-001"
    assert production.release.dev_only is False
    assert calibration.release.dev_only is True
    assert production.corpus.max_scan_shards == 105
    assert calibration.corpus.max_scan_shards == 20
    assert production.extraction.materialize_cap == 38_000
    assert calibration.extraction.materialize_cap is None
    assert production.person.reject_role == "main_subject"
    assert "painting or artwork" in production.classify.labels
    assert production.neardup.similarity_threshold == 0.97
    assert production.providers.encoder.provider == (
        "voyage" if encoder == "voyage" else "openrouter")
    # The two runs share each provider slot, thus the calibration answers
    # are the production run's cache.
    for name in ("screener", "encoder"):
        assert getattr(production.providers, name) == getattr(calibration.providers, name)
    assert production.classify == calibration.classify


@pytest.mark.parametrize(("encoder", "cell", "boxes"), [
    ("voyage", "inst", "deferred"), ("voyage", "plain", "deferred"),
    ("gemini", "inst", "deferred"), ("voyage", "inst", "bought"),
])
def test_the_lineage_documents_parse_and_agree(
        production_release: str, encoder: str, cell: str, boxes: str,
        tmp_path: Path) -> None:
    documents = writer.lineage_documents(
        rulings(encoder=encoder, cell=cell, boxes=boxes), production_release)
    preparation = parse_preparation_config(
        documents["preparation/prod-wit-photo-inst.json"])
    assert preparation.elements.normalize_rule == "d8-v1"
    assert preparation.neardup.similarity_threshold == 0.96
    assert preparation.release.dev_only is False
    fit_path = tmp_path / "fit.json"
    fit_path.write_text(json.dumps(documents["fit/prod-wit.json"]))
    assert load_fit_config(fit_path).generalize.normalize_rule == "d8-v1"
    record = writer.preparation_record_path(
        documents["preparation/prod-wit-photo-inst.json"])
    scoring = [parse_scoring_config(documents[f"scoring/{name}.json"]) for name in
               ("prod-wit-b", "prod-wit-mixed", "prod-wit-photo-inst-sym")]
    for config in scoring:
        assert config.input.preparation_record == record
        assert not config.input.preparation_record.split("/")[-1].startswith("dev-")
        assert config.report.dev_only is False
        harness.check_outline_space(config, preparation)
        # The gates and the server read one commonness source.
        assert config.commonness == scoring[0].commonness
        assert config.commonness.synthetic is not None
        assert ("placement" in dict(config.fusion.weights)) == (boxes == "bought")
    if cell == "plain":
        assert preparation.providers.image_encoder.instruction_template is None
        assert scoring[0].providers.sketch_encoder.instruction_template is None
    else:
        assert preparation.providers.image_encoder.instruction_template is not None


def test_a_development_release_is_refused() -> None:
    with pytest.raises(ValueError, match="development release"):
        writer.lineage_documents(rulings(), "pool/releases/dev-wit-002-9644fac1.json")


def test_an_existing_file_is_not_overwritten(tmp_path: Path) -> None:
    writer.write_documents({"a/b.json": {"x": 1}}, tmp_path)
    with pytest.raises(FileExistsError):
        writer.write_documents({"a/b.json": {"x": 2}}, tmp_path)
    assert json.loads((tmp_path / "a/b.json").read_text()) == {"x": 1}


def test_no_committed_prod_config_names_a_dev_input() -> None:
    """B5: this guard reads each file the tool writes, after its commit."""
    for path in Path("configs").glob("*/prod-*.json"):
        document = json.loads(path.read_text())
        for key in ("release_record", "preparation_record"):
            value = document.get("input", {}).get(key, "")
            assert "/dev-" not in value, f"{path} names {value}"
        release = document.get("release", {})
        assert release.get("dev_only") is not True, path


def _tree(root: Path, name: str, fetched: list[str], released: list[str] | None) -> Path:
    tree = root / name
    (tree / "s02-materialize").mkdir(parents=True)
    (tree / "s02-materialize" / "manifest.jsonl").write_text(
        "".join(json.dumps({"image_id": item}) + "\n" for item in fetched))
    if released is not None:
        (tree / "s09-release").mkdir()
        (tree / "s09-release" / "manifest.jsonl").write_text(
            "".join(json.dumps({"image_id": item}) + "\n" for item in released))
    return tree


def test_the_prune_plan_keeps_released_and_unfinished_images(tmp_path: Path) -> None:
    done = _tree(tmp_path, "done", ["a", "b", "c", "shared"], ["a"])
    other = _tree(tmp_path, "other", ["d", "a"], ["d"])
    running = _tree(tmp_path, "running", ["shared", "e"], None)
    plan = prune_plan([done, other, running])
    assert plan.remove == ("b", "c")
    assert plan.kept_released == 2
    assert plan.kept_incomplete == 2


def test_a_tree_with_no_fetch_stage_adds_nothing(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert prune_plan([tmp_path / "empty"]).remove == ()


def screened_config():
    slot = {"provider": "screener", "model": None, "instruction_template": None,
            "dimension": None, "probability_sum_tolerance": None}
    return make_config(**{
        "providers.text_coverage": slot, "providers.classifier": slot,
        "providers.object_size": slot,
        "providers.screener": {"provider": "fake", "model": None,
                               "instruction_template": None, "input_canvas_px": None},
    }, person={"reject_role": "main_subject"})


@pytest.mark.parametrize(("text", "label", "size", "person", "expected"), [
    (0.0, "photograph", 0.5, 0.0, "kept"),
    (0.5, "diagram", 0.0, 1.0, "text-coverage"),
    (0.0, "coat of arms", 0.0, 1.0, "class-coat-of-arms"),
    (0.0, "photograph", 0.1, 1.0, "object-size"),
    (0.0, "photograph", 0.5, 1.0, "person-focus"),
])
def test_the_group_is_the_first_rule_in_stage_sequence(
        text: float, label: str, size: float, person: float, expected: str) -> None:
    assert screener_check.screen_group(text, label, size, person,
                                       screened_config()) == expected


def test_the_sheet_holds_a_section_for_each_group() -> None:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.fromarray(np.zeros((8, 8, 3), dtype=np.uint8)).save(buffer, "PNG")
    image = buffer.getvalue()
    page = screener_check.sheet_html([("a", "kept", image), ("b", "person-focus", image),
                                      ("c", "person-focus", image)])
    assert "person-focus (2)" in page
    assert page.index("person-focus") < page.index("kept (1)")


def test_the_dev_screener_config_holds_the_production_instruction() -> None:
    """The owner's check must read the wording the production run sends."""
    document = json.loads(Path("configs/curation/dev-wit-screener.json").read_text())
    config = parse_curation_config(document)
    assert config.providers.screener.instruction_template == writer.SCREENER_INSTRUCTION
    assert tuple(config.classify.labels) == writer.PRODUCTION_LABELS
    assert config.release.dev_only is True
