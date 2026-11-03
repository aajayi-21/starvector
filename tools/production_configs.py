"""Write the production configs of spec PP1 from the rulings.

Spec: docs/specs/production-pool.md build items B1, B2, and B4. The
production configs read the bake-off verdict of spec VE1 and the owner's
near-duplicate rulings, thus they cannot be committed before those
numbers. This tool holds the parameter tables, a test parses its output
for each encoder, and the owner runs it one time for each step. It reads
the committed development configs, and no value here moves a stored
config.
"""

import argparse
import copy
import json
from pathlib import Path
from typing import NamedTuple

from pool.preparation import manifest as mf
from pool.preparation.config import (parse_preparation_config,
                                     preparation_config_hash)
from pool.preparation.run import provider_config_hashes
from pool.preparation.stages.release import (release_label,
                                             release_preparation_version_id)

VOYAGE_MODEL = "voyage-multimodal-3.5"
VOYAGE_DIMENSION = 1024
PRODUCTION_LABELS = (
    "photograph", "diagram", "chart", "logo", "map", "screenshot",
    "coat of arms", "line drawing", "painting or artwork", "document or scan",
)
SCREENER_INSTRUCTION = (
    "Examine the image and return a JSON object with these fields. "
    "text_area_fraction: the fraction of the image area that is covered by "
    "rendered or overlaid text of any kind, including captions, labels, "
    "watermarks, and signs, as a number between 0 and 1. "
    "label: the one category that fits best, from {label_phrases}. "
    "confidence: your confidence in that label, as a number between 0 and 1. "
    "largest_object_fraction: the fraction of the image area that the single "
    "largest distinct foreground object covers, as a number between 0 and 1. "
    "If there is no distinct object, use 0. "
    "person_role: use \"main_subject\" when a person or a face is what the "
    "image is mainly of, such as a portrait, a posed group, or a close view "
    "of people. Use \"in_scene\" when people appear but a place, an object, or "
    "an event is the subject, such as a street, a market, or a building with "
    "visitors. Use \"none\" when no person appears. Return JSON only."
)
_BOX_INSTRUCTION_SOURCE = "configs/preparation/dev-wit-photo-inst-2.json"


class Rulings(NamedTuple):
    """The owner's values that the tool cannot know.

    encoder and cell come from the spec VE1 verdict, the threshold from
    the calibration, and boxes from the budget ruling (PP1 ruling 11).
    """

    encoder: str                 # "voyage" | "gemini"
    cell: str                    # "inst" | "plain"
    curation_threshold: float
    preparation_threshold: float
    boxes: str                   # "deferred" | "bought"
    materialize_cap: int


def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _encoder_fields(rulings: Rulings) -> dict:
    if rulings.encoder == "voyage":
        return {"provider": "voyage", "model": VOYAGE_MODEL,
                "dimension": VOYAGE_DIMENSION}
    return {"provider": "openrouter", "model": "google/gemini-embedding-2",
            "dimension": 3072}


def _screening_config(rulings: Rulings) -> dict:
    """The fields that the calibration and production configs share."""
    document = _read("configs/curation/dev-wit-2.json")
    document["classify"]["labels"] = list(PRODUCTION_LABELS)
    document["neardup"]["similarity_threshold"] = rulings.curation_threshold
    document["extraction"]["budget_bytes"] = 20_000_000_000
    providers = document["providers"]
    slot = {"provider": "screener", "model": None, "instruction_template": None,
            "dimension": None, "probability_sum_tolerance": None}
    providers["text_coverage"] = dict(slot)
    providers["classifier"] = dict(slot)
    providers["object_size"] = dict(slot)
    providers["screener"] = {"provider": "openrouter", "model": None,
                             "instruction_template": SCREENER_INSTRUCTION,
                             "input_canvas_px": 512}
    providers["encoder"].update(_encoder_fields(rulings))
    document["person"] = {"reject_role": "main_subject"}
    return document


def curation_documents(rulings: Rulings) -> dict[str, dict]:
    """B1 and B2: the production curation and its calibration run."""
    production = _screening_config(rulings)
    production["corpus"]["max_scan_shards"] = 105
    production["extraction"]["materialize_cap"] = rulings.materialize_cap
    production["release"] = {"tag": "prod-wit-001", "dev_only": False}
    calibration = _screening_config(rulings)
    calibration["corpus"]["max_scan_shards"] = 20
    calibration["extraction"]["materialize_cap"] = None
    calibration["release"] = {"tag": "dev-wit-003", "dev_only": True}
    return {"curation/prod-wit.json": production,
            "curation/dev-wit-3.json": calibration}


def _preparation(rulings: Rulings, release_record: str) -> dict:
    document = _read(_BOX_INSTRUCTION_SOURCE)
    document["input"]["release_record"] = release_record
    document["elements"]["normalize_rule"] = "d8-v1"
    document["neardup"]["similarity_threshold"] = rulings.preparation_threshold
    providers = document["providers"]
    providers["image_encoder"].update(_encoder_fields(rulings))
    providers["text_encoder"].update(_encoder_fields(rulings))
    if rulings.cell == "plain":
        providers["image_encoder"]["instruction_template"] = None
    if rulings.boxes == "deferred":
        providers["element_boxes"] = {"provider": "deferred", "model": None,
                                      "instruction_template": None,
                                      "dimension": None}
    document["release"] = {"tag": "prod-wit-photo-inst", "dev_only": False}
    return document


def preparation_record_path(document: dict) -> str:
    """The record name the run gives this config, known before the run."""
    config = parse_preparation_config(document)
    release = mf.parse_release_record(Path(config.input.release_record))
    version = release_preparation_version_id(
        release.pool_version_id,
        preparation_config_hash(config, provider_config_hashes(config)))
    return f"pool/preparations/{release_label(config.release.tag, version)}.json"


def _scoring(rulings: Rulings, record_path: str, tag: str, mode: str) -> dict:
    """One scoring config on the source-B commonness tables.

    The gates and the server read one commonness source, thus V5 describes
    the served tables. Weights stay at the candidate table until the
    freeze edit of the F1 sequence.
    """
    document = _read("configs/scoring/dev-wit-b-2.json")
    document["input"]["preparation_record"] = record_path
    document["commonness"]["synthetic"]["fit_config"] = "configs/fit/prod-wit.json"
    weights = {"outline": 1.0, "element": 1.0}
    if rulings.boxes == "bought":
        weights["placement"] = 1.0
    document["fusion"] = {"weights": weights, "fit_record": None}
    providers = document["providers"]
    providers["sketch_encoder"].update(_encoder_fields(rulings))
    providers["text_encoder"].update(_encoder_fields(rulings))
    if rulings.cell == "plain":
        providers["sketch_encoder"]["instruction_template"] = None
    document["validation"]["tag"] = tag
    document["validation"]["submission_mode"] = mode
    document["report"]["dev_only"] = False
    return document


def lineage_documents(rulings: Rulings, release_record: str) -> dict[str, dict]:
    """B4: preparation, fit, and scoring configs on one released pool."""
    release = mf.parse_release_record(Path(release_record))
    if release.dev_only:
        raise ValueError(
            f"{release_record} is a development release: no prod- config "
            "names one (spec PP1 B5)")
    preparation = _preparation(rulings, release_record)
    record_path = preparation_record_path(preparation)
    fit = _read("configs/fit/dev-wit-2.json")
    fit["tag"] = "prod-wit"
    fit["generalize"]["normalize_rule"] = "d8-v1"
    return {
        "preparation/prod-wit-photo-inst.json": preparation,
        "fit/prod-wit.json": fit,
        "scoring/prod-wit-b.json": _scoring(
            rulings, record_path, "prod-wit-b", "mixed"),
        "scoring/prod-wit-mixed.json": _scoring(
            rulings, record_path, "prod-wit-mixed", "mixed"),
        "scoring/prod-wit-photo-inst-sym.json": _scoring(
            rulings, record_path, "prod-wit-photo-inst-sym", "sketch"),
    }


def write_documents(documents: dict[str, dict], root: Path) -> list[Path]:
    """Write each document below root. A file on disk is not overwritten:
    an edit to a released lineage is a new lineage, not a new write."""
    written: list[Path] = []
    for relative, document in documents.items():
        path = root / relative
        if path.exists():
            raise FileExistsError(f"{path} exists - remove it deliberately first")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.production_configs")
    parser.add_argument("step", choices=("curation", "lineage"))
    parser.add_argument("--encoder", required=True, choices=("voyage", "gemini"))
    parser.add_argument("--cell", default="inst", choices=("inst", "plain"))
    parser.add_argument("--curation-threshold", type=float, required=True)
    parser.add_argument("--preparation-threshold", type=float, required=True)
    parser.add_argument("--boxes", default="deferred", choices=("deferred", "bought"))
    parser.add_argument("--materialize-cap", type=int, default=38_000)
    parser.add_argument("--release-record", help="required for the lineage step")
    parser.add_argument("--root", type=Path, default=Path("configs"))
    arguments = parser.parse_args(argv)
    rulings = Rulings(
        encoder=arguments.encoder, cell=arguments.cell,
        curation_threshold=arguments.curation_threshold,
        preparation_threshold=arguments.preparation_threshold,
        boxes=arguments.boxes, materialize_cap=arguments.materialize_cap)
    if arguments.step == "curation":
        documents = curation_documents(rulings)
    else:
        if arguments.release_record is None:
            parser.error("the lineage step requires --release-record")
        documents = lineage_documents(rulings, arguments.release_record)
    for path in write_documents(documents, arguments.root):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
