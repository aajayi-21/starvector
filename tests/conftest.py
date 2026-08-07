"""Shared fixtures for the curation test suite.

All tests run offline against the fake corpus and fake providers. The
fixtures build small configs, run the pipeline in-process, and compare
artifact trees byte-for-byte.
"""

import json
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from core.canonical import canonical_json, canonical_json_pretty, sha256_hex
from pool import artifacts
from pool.curation.config import CurationConfig, parse_curation_config
from pool.curation.run import run_curation
from pool.curation.stages.release import pool_version_id
from pool.curation.types import RunReport
from pool.preparation.config import PreparationConfig, parse_preparation_config
from pool.preparation.run import run_preparation
from pool.preparation.types import PreparationReport

FIXED_CLOCK = "2026-01-01T00:00:00+00:00"

# The default fake population: each rule has records on the two sides
# of its boundary. Counts stay small so the suite stays fast.
DEFAULT_POPULATION: tuple[tuple[str, int], ...] = (
    ("photo", 40),
    ("lowres", 5),
    ("lowres_lying", 3),
    ("no_metadata", 4),
    ("bad_aspect", 3),
    ("aspect_boundary", 2),
    ("undecodable", 2),
    ("fetch_fail", 2),
    ("dup_bytes", 3),
    ("text_heavy", 5),
    ("text_boundary", 2),
    ("diagram", 5),
    ("logo", 2),
    ("map_like", 2),
    ("small_object", 5),
    ("no_object", 2),
    ("object_boundary", 2),
    ("neardup_pair", 4),
    ("cluster_family", 20),
)


def base_config_dict(**overrides) -> dict:
    """The raw JSON document for a fake-provider test config."""
    document = {
        "config_version": 1,
        "corpus": {
            "provider": "fake",
            "repo_id": "fake/fake-corpus",
            "revision": "fixed",
            "config_name": None,
            "split": "train",
            "columns": {
                "source_key": "source_key",
                "claimed_width": "claimed_width",
                "claimed_height": "claimed_height",
                "captions": ["caption"],
                "attribution": ["source_key"],
            },
            "license_note": "test",
            "max_scan_shards": None,
            "materialization": {
                "mode": "fake",
                "thumbnail_width": 1280,
                "user_agent": "test-agent/0.0",
                "max_concurrency": 1,
                "timeout_seconds": 5.0,
                "retry_limit": 0,
                "fetch_batch_size": 16,
                "max_fetch_bytes": 50000000,
            },
        },
        "sampling": {"sample_salt": "test-salt", "sample_rate": 1.0},
        "extraction": {"budget_bytes": 10**9, "materialize_cap": None},
        "screen": {"min_short_side": 512, "min_aspect": 0.5, "max_aspect": 2.0},
        "text": {"max_text_coverage": 0.05},
        "classify": {
            "labels": [
                "photograph", "diagram", "chart", "logo", "map",
                "screenshot", "coat of arms", "line drawing",
            ],
            "keep_label": "photograph",
            "label_template": "a {label}",
        },
        "objectsize": {"min_object_fraction": 0.15},
        "neardup": {"similarity_threshold": 0.95},
        "diversity": {
            "cluster_size_divisor": 50,
            "cluster_cap": 15,
            "kmeans_max_iterations": 100,
        },
        "review": {"sample_size": 200, "thumbnail_max_side": 128},
        "providers": {
            "openrouter": {
                "default_model": "google/gemini-3.1-flash-lite",
                "max_concurrency": 1,
                "requests_per_second": 100.0,
                "timeout_seconds": 5.0,
                "retry_limit": 0,
                "response_format_mode": "json_schema",
            },
            "text_coverage": {
                "provider": "fake", "model": None, "instruction_template": None,
                "dimension": None, "probability_sum_tolerance": None,
            },
            "classifier": {
                "provider": "fake", "model": None, "instruction_template": None,
                "dimension": None, "probability_sum_tolerance": None,
            },
            "object_size": {
                "provider": "fake", "model": None, "instruction_template": None,
                "dimension": None, "probability_sum_tolerance": None,
            },
            "encoder": {
                "provider": "fake", "model": None, "instruction_template": None,
                "dimension": 64, "probability_sum_tolerance": None,
            },
        },
        "seeds": {"cluster_seed": 7, "review_seed": 11},
        "release": {"tag": "dev-test", "dev_only": True},
    }
    for dotted, value in overrides.items():
        node = document
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return document


def make_config(**overrides) -> CurationConfig:
    return parse_curation_config(base_config_dict(**overrides), "test-config")


def make_fake_corpus(population=DEFAULT_POPULATION, scan_bytes_per_record: int = 100):
    from providers.corpora.fake import FakeCorpus, FakeCorpusConfig, FakeRecordSpec

    specs = tuple(FakeRecordSpec(name, count) for name, count in population)
    return FakeCorpus(FakeCorpusConfig(records=specs, scan_bytes_per_record=scan_bytes_per_record))


def run_pipeline(
    config: CurationConfig,
    data_root: Path,
    releases_root: Path,
    *,
    population=DEFAULT_POPULATION,
    through: str | None = None,
    force_from: str | None = None,
) -> RunReport:
    return run_curation(
        config,
        config_path=Path("test-config.json"),
        data_root=data_root,
        releases_root=releases_root,
        code_version="test",
        through=through,
        force_from=force_from,
        corpus=make_fake_corpus(population),
        clock=lambda: FIXED_CLOCK,
    )


def find_stage_dir(data_root: Path, stage: str) -> Path:
    matches = list(data_root.glob(f"curation/*/*/{stage}"))
    assert len(matches) == 1, f"expected one {stage} directory, found {matches}"
    return matches[0]


def write_review(data_root: Path, verdict: str = "pass") -> Path:
    directory = find_stage_dir(data_root, "s08-review")
    path = directory / "review.json"
    record = {
        "verdict": verdict,
        "reviewer": "test",
        "date": "2026-01-01T00:00:00Z",
        "notes": "",
    }
    path.write_text(canonical_json_pretty(record) + "\n", encoding="utf-8")
    return path


def read_stage_jsonl(data_root: Path, stage: str, name: str) -> list[dict]:
    path = find_stage_dir(data_root, stage) / name
    return [json.loads(line) for line in path.read_text().splitlines()]


def assert_trees_identical(a: Path, b: Path, exclude_names: tuple[str, ...] = ("timings.json",)):
    files_a = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    files_a = {p for p in files_a if p.name not in exclude_names}
    files_b = {p for p in files_b if p.name not in exclude_names}
    assert files_a == files_b, f"tree file sets differ: {files_a ^ files_b}"
    for rel in sorted(files_a):
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), f"file differs: {rel}"


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def releases_root(tmp_path: Path) -> Path:
    return tmp_path / "releases"


@pytest.fixture(scope="module")
def completed_run(tmp_path_factory: pytest.TempPathFactory):
    """One full fake run through s09, shared by read-only tests."""
    root = tmp_path_factory.mktemp("completed")
    data = root / "data"
    releases = root / "releases"
    config = make_config()
    first = run_pipeline(config, data, releases)
    assert first.halted_at == "s08-review" and first.halt_reason == "awaiting-review"
    write_review(data, "pass")
    report = run_pipeline(config, data, releases)
    assert report.halted_at is None and report.pool_version_id is not None
    return {"data": data, "releases": releases, "config": config, "report": report}


# --- preparation (P1b) fixtures --------------------------------------------

PREP_ELEMENT_BASE: dict = {
    "objects": ["tree", "bench", "path"],
    "materials": ["wood", "stone", "gravel"],
    "colors": ["green", "brown", "grey"],
    "shapes": ["vertical trunk", "horizontal slat"],
    "scale": "medium",
    "setting": "outdoor park",
    "ambience": ["calm", "quiet", "open"],
}

# The default pool of eight images: a near-duplicate pair in fam-a, far
# members of fam-b, chunk-free images, and element sets that mix shared
# strings, unique strings, plural forms, and articles. One image
# scripts a null box for one of its elements.
PrepImageSpec = tuple[dict, str | None, str | None, dict]
PREP_DEFAULT_SPECS: tuple[PrepImageSpec, ...] = (
    ({}, "fam-a", "dup", {}),
    ({"objects": ["trees", "bench", "kite"]}, "fam-a", "dup", {}),
    (
        {"objects": ["windmill", "canal", "tulip"], "setting": "outdoor polder"},
        "fam-b", "far", {},
    ),
    (
        {
            "objects": ["lighthouse", "breakwater", "gull"],
            "materials": ["stone", "metal", "seawater"],
            "colors": ["white", "red", "blue"],
        },
        "fam-b", "far", {},
    ),
    (
        {"objects": ["a tree", "the bench", "fountain"],
         "ambience": ["calm", "misty", "still"]},
        "fam-c", "far", {},
    ),
    ({"objects": ["cat", "sofa", "lamp"], "scale": "small",
      "setting": "indoor lounge"}, None, None, {}),
    (
        {"objects": ["mountain", "glacier", "valley"], "scale": "large",
         "colors": ["white", "blue", "slate"]},
        None, None, {"fake_boxes": '{"mountain": null}'},
    ),
    ({"objects": ["crate", "pallet", "drum"],
      "materials": ["cardboard", "pine", "plastic"]}, "fam-d", "far", {}),
)


def build_released_pool(
    data_root: Path, record_dir: Path, specs: Sequence[PrepImageSpec]
) -> dict:
    """Hand-build one released pool: image store, s09 manifest, record.

    Each spec is a four-part tuple: overrides for the scripted
    seven-field describer response, an embed family, an embed jitter,
    and added PNG text chunks. A None family or jitter writes no chunk.
    The record has the dev_only flag set and a "dev-" label. The output
    maps record_path, pool_version_id, image_ids (ascending), and
    label.
    """
    image_ids: list[str] = []
    for position, (overrides, family, jitter, added_chunks) in enumerate(specs):
        elements = {**PREP_ELEMENT_BASE, **overrides}
        info = PngInfo()
        info.add_text("fake_elements", canonical_json(elements))
        if family is not None:
            info.add_text("embed_family", family)
        if jitter is not None:
            info.add_text("embed_jitter", jitter)
        for chunk_key, chunk_value in sorted(added_chunks.items()):
            info.add_text(chunk_key, chunk_value)
        # A position-derived color keeps each image's bytes unique.
        color = ((37 * position) % 256, (91 * position) % 256, 40)
        buffer = BytesIO()
        Image.new("RGB", (64, 64), color=color).save(buffer, format="PNG", pnginfo=info)
        image_ids.append(artifacts.store_image_bytes(data_root, buffer.getvalue()))
    image_ids.sort()
    corpus_id = sha256_hex("prep-test-corpus")
    curation_hash = sha256_hex("prep-test-curation-config")
    manifest_dir = data_root / "curation" / corpus_id[:8] / curation_hash[:8] / "s09-release"
    artifacts.write_jsonl(
        manifest_dir / "manifest.jsonl",
        [
            {"image_id": image_id, "source_key": f"fake://{image_id[:12]}"}
            for image_id in image_ids
        ],
    )
    pool_version = pool_version_id(corpus_id, curation_hash, image_ids)
    label = f"dev-pool-{pool_version[:8]}"
    record = {
        "label": label,
        "pool_version_id": pool_version,
        "corpus_id": corpus_id,
        "curation_config_hash": curation_hash,
        "corpus_identity": {
            "provider": "fake", "repo_id": "fake/fake-corpus", "revision": "fixed",
            "config_name": None, "split": "train",
        },
        "config_path": "configs/curation/dev-wit.json",
        "image_count": len(image_ids),
        "funnel": {},
        "review": {"verdict": "pass", "reviewer": "test", "date": FIXED_CLOCK, "notes": ""},
        "dev_only": True,
        "code_version": "test",
        "created_at": FIXED_CLOCK,
    }
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"{label}.json"
    record_path.write_text(canonical_json_pretty(record) + "\n", encoding="utf-8")
    return {
        "record_path": record_path,
        "pool_version_id": pool_version,
        "image_ids": image_ids,
        "label": label,
    }


def prep_config_dict(record_path: Path | str, **overrides) -> dict:
    """The raw JSON document for a fake-provider preparation config."""
    document = {
        "config_version": 1,
        "input": {"release_record": str(record_path)},
        "elements": {
            "counts": {
                "objects": 3, "materials": 3, "colors": 3, "shapes": 2,
                "scale": 1, "setting": 1, "ambience": 3,
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
                "default_model": "test/fake-model",
                "max_concurrency": 1,
                "requests_per_second": 100.0,
                "timeout_seconds": 5.0,
                "retry_limit": 0,
                "response_format_mode": "json_schema",
            },
            "describer": {
                "provider": "fake", "model": None,
                "instruction_template": None, "dimension": None,
            },
            "text_encoder": {
                "provider": "fake", "model": None,
                "instruction_template": None, "dimension": 32,
            },
            "image_encoder": {
                "provider": "fake", "model": None,
                "instruction_template": None, "dimension": 32,
            },
            "line_drawer": {
                "provider": "fake", "model": None,
                "instruction_template": None, "dimension": None,
            },
            "element_boxes": {
                "provider": "fake", "model": None,
                "instruction_template": None, "dimension": None,
            },
        },
        "runtime": {"device": "cpu"},
        "release": {"tag": "dev-test-prep", "dev_only": True},
    }
    for dotted, value in overrides.items():
        node = document
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return document


def make_prep_config(record_path: Path | str, **overrides) -> PreparationConfig:
    return parse_preparation_config(
        prep_config_dict(record_path, **overrides), "test-prep-config"
    )


def run_prep(
    config: PreparationConfig,
    data_root: Path,
    prep_releases_root: Path,
    *,
    through: str | None = None,
    force_from: str | None = None,
    providers: Mapping[str, object] | None = None,
) -> PreparationReport:
    return run_preparation(
        config,
        config_path=Path("test-prep-config.json"),
        data_root=data_root,
        releases_root=prep_releases_root,
        code_version="test",
        through=through,
        force_from=force_from,
        providers=providers,
        clock=lambda: FIXED_CLOCK,
    )


def find_prep_stage_dir(data_root: Path, stage: str) -> Path:
    matches = list(data_root.glob(f"preparation/*/*/{stage}"))
    assert len(matches) == 1, f"expected one {stage} directory, found {matches}"
    return matches[0]


def read_prep_stage_jsonl(data_root: Path, stage: str, name: str) -> list[dict]:
    path = find_prep_stage_dir(data_root, stage) / name
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.fixture(scope="module")
def completed_preparation(tmp_path_factory: pytest.TempPathFactory):
    """One full preparation of the default released pool, shared by read-only tests."""
    root = tmp_path_factory.mktemp("completed-prep")
    data = root / "data"
    releases = root / "releases"
    pool = build_released_pool(data, root / "pool-releases", PREP_DEFAULT_SPECS)
    config = make_prep_config(pool["record_path"])
    report = run_prep(config, data, releases)
    assert report.preparation_version_id is not None
    assert not any(entry.skipped for entry in report.stages)
    return {
        "data": data,
        "releases": releases,
        "config": config,
        "report": report,
        "pool": pool,
    }
