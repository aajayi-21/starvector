"""Shared fixtures for the curation test suite.

All tests run offline against the fake corpus and fake providers. The
fixtures build small configs, run the pipeline in-process, and compare
artifact trees byte-for-byte.
"""

import json
from pathlib import Path

import pytest

from core.canonical import canonical_json_pretty
from pool.curation.config import CurationConfig, parse_curation_config
from pool.curation.run import run_curation
from pool.curation.types import RunReport

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
