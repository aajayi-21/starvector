"""End-to-end fake preparation: artifact tree, committed record, coverage."""

import json
from pathlib import Path

import numpy as np

from conftest import (
    PREP_DEFAULT_SPECS,
    build_released_pool,
    find_prep_stage_dir,
    make_prep_config,
    read_prep_stage_jsonl,
    run_prep,
)

from core.canonical import sha256_hex
from pool.artifacts import load_image_bytes
from pool.preparation.types import STAGE_NAMES
from providers.fake.chunks import read_fake_chunks

# The data files of each stage directory (spec section 11).
_STAGE_DATA_FILES: dict[str, tuple[str, ...]] = {
    "p00-intake": ("records.jsonl",),
    "p01-elements": ("elements.jsonl",),
    "p02-normalize": ("normalized.jsonl",),
    "p03-cap": ("capped.jsonl", "cuts.jsonl"),
    "p04-vocabulary": (
        "vocabulary.jsonl", "vocabulary_vectors.npy", "incidence.npy",
        "element_space_mean.npy",
    ),
    "p05-linedraw": ("drawings.jsonl",),
    "p06-outline": ("outline_vectors.npy", "outline_space_mean.npy"),
    "p07-boxes": ("boxes.jsonl",),
    "p08-neardup": ("groups.jsonl",),
    "p09-release": (),
}

# The jsonl files with one row for each pool image.
_MEMBERSHIP_FILES: tuple[tuple[str, str], ...] = (
    ("p00-intake", "records.jsonl"),
    ("p01-elements", "elements.jsonl"),
    ("p02-normalize", "normalized.jsonl"),
    ("p03-cap", "capped.jsonl"),
    ("p05-linedraw", "drawings.jsonl"),
    ("p07-boxes", "boxes.jsonl"),
    ("p08-neardup", "groups.jsonl"),
)

# The pinned top-level key set of the committed record (spec, stage p09).
_RECORD_KEYS = {
    "label", "preparation_version_id", "pool", "preparation_config_hash",
    "config_path", "image_count", "artifacts", "provider_config_hashes",
    "provider_usage", "dev_only", "code_version", "created_at",
}

_SLOTS = {"describer", "text_encoder", "image_encoder", "line_drawer", "element_boxes"}


def test_full_fake_run_creates_complete_artifact_tree(completed_preparation):
    data = completed_preparation["data"]
    for stage in STAGE_NAMES:
        directory = find_prep_stage_dir(data, stage)
        assert (directory / "meta.json").exists(), stage
        for name in _STAGE_DATA_FILES[stage]:
            assert (directory / name).exists(), f"{stage}/{name}"


def test_photo_outline_source_bypasses_p05_and_writes_six_rows(
    tmp_path,
) -> None:
    data = tmp_path / "data"
    pool = build_released_pool(
        data, tmp_path / "pool-releases", PREP_DEFAULT_SPECS
    )
    config = make_prep_config(
        pool["record_path"], **{"outline.source": "photo"}
    )
    report = run_prep(
        config, data, tmp_path / "preparation-releases", through="p06"
    )

    p05 = next(stage for stage in report.stages if stage.stage == "p05-linedraw")
    p05_directory = find_prep_stage_dir(data, "p05-linedraw")
    p05_meta = json.loads((p05_directory / "meta.json").read_text())
    assert p05.provider_posts == 0
    assert p05.provider_cache_hits == 0
    assert p05_meta["config_echo"] == {"source": "photo"}
    assert p05_meta["provider_config_hashes"] == {}
    assert not (p05_directory / "drawings.jsonl").exists()

    vectors = np.load(
        find_prep_stage_dir(data, "p06-outline") / "outline_vectors.npy"
    )
    assert vectors.shape[:2] == (len(pool["image_ids"]), 6)


def test_committed_record_agrees_with_the_tree(completed_preparation):
    report = completed_preparation["report"]
    record = json.loads(Path(report.release_record_path).read_text())
    assert set(record) == _RECORD_KEYS
    assert record["dev_only"] is True
    assert record["label"].startswith("dev-")
    assert record["label"] == report.release_label
    assert record["preparation_version_id"] == report.preparation_version_id
    assert record["preparation_config_hash"] == report.preparation_config_hash
    pool = completed_preparation["pool"]
    assert record["pool"]["pool_version_id"] == pool["pool_version_id"]
    assert record["pool"]["label"] == pool["label"]
    assert record["image_count"] == len(pool["image_ids"])
    assert set(record["provider_config_hashes"]) == _SLOTS
    assert set(record["provider_usage"]) == _SLOTS
    for slot_usage in record["provider_usage"].values():
        assert set(slot_usage) == {"posts", "cache_hits"}
        assert all(isinstance(value, int) for value in slot_usage.values())
    # The artifact inventory names each data file and no meta or
    # timings file, and each stored digest agrees with the bytes.
    expected_files = {
        f"{stage}/{name}"
        for stage, names in _STAGE_DATA_FILES.items()
        for name in names
    }
    assert set(record["artifacts"]) == expected_files
    tree_root = find_prep_stage_dir(completed_preparation["data"], "p00-intake").parent
    for relative, digest in record["artifacts"].items():
        assert sha256_hex((tree_root / relative).read_bytes()) == digest, relative


def test_artifacts_cover_the_membership_ascending(completed_preparation):
    data = completed_preparation["data"]
    membership = completed_preparation["pool"]["image_ids"]
    assert membership == sorted(membership)
    for stage, name in _MEMBERSHIP_FILES:
        rows = read_prep_stage_jsonl(data, stage, name)
        assert [row["image_id"] for row in rows] == membership, f"{stage}/{name}"
    count = len(membership)
    incidence = np.load(find_prep_stage_dir(data, "p04-vocabulary") / "incidence.npy")
    assert incidence.shape[0] == count
    outline = np.load(find_prep_stage_dir(data, "p06-outline") / "outline_vectors.npy")
    assert outline.shape[0] == count


def test_capped_element_sequences_stay_at_or_below_the_cap(completed_preparation):
    cap = completed_preparation["config"].elements.max_elements
    rows = read_prep_stage_jsonl(completed_preparation["data"], "p03-cap", "capped.jsonl")
    for row in rows:
        assert 0 < len(row["elements"]) <= cap, row["image_id"]


def test_incidence_rows_decode_to_the_capped_sequences(completed_preparation):
    data = completed_preparation["data"]
    vocabulary_rows = read_prep_stage_jsonl(data, "p04-vocabulary", "vocabulary.jsonl")
    assert [row["index"] for row in vocabulary_rows] == list(range(len(vocabulary_rows)))
    vocabulary = [row["element"] for row in vocabulary_rows]
    assert vocabulary == sorted(vocabulary)
    capped = read_prep_stage_jsonl(data, "p03-cap", "capped.jsonl")
    incidence = np.load(find_prep_stage_dir(data, "p04-vocabulary") / "incidence.npy")
    assert incidence.dtype == np.int32
    for position, row in enumerate(capped):
        entries = row["elements"]
        decoded = [vocabulary[index] for index in incidence[position, : len(entries)]]
        assert decoded == entries, row["image_id"]
        assert (incidence[position, len(entries):] == -1).all(), row["image_id"]


def test_stored_vectors_are_unit_norm_with_the_documented_shapes(completed_preparation):
    data = completed_preparation["data"]
    config = completed_preparation["config"]
    count = len(completed_preparation["pool"]["image_ids"])
    vocabulary_dir = find_prep_stage_dir(data, "p04-vocabulary")
    vectors = np.load(vocabulary_dir / "vocabulary_vectors.npy")
    text_dimension = config.providers.text_encoder.dimension
    entry_count = len(read_prep_stage_jsonl(data, "p04-vocabulary", "vocabulary.jsonl"))
    assert vectors.dtype == np.float32
    assert vectors.shape == (entry_count, text_dimension)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-3)
    outline_dir = find_prep_stage_dir(data, "p06-outline")
    outline = np.load(outline_dir / "outline_vectors.npy")
    image_dimension = config.providers.image_encoder.dimension
    assert outline.dtype == np.float32
    assert outline.shape == (count, 6, image_dimension)
    stacked_rows = outline.reshape(-1, image_dimension)  # (N * 6, d)
    assert np.allclose(np.linalg.norm(stacked_rows, axis=1), 1.0, atol=1e-3)
    assert np.load(vocabulary_dir / "element_space_mean.npy").shape == (text_dimension,)
    assert np.load(outline_dir / "outline_space_mean.npy").shape == (image_dimension,)


def test_groups_are_a_partition_that_agrees_with_the_cosines(completed_preparation):
    data = completed_preparation["data"]
    membership = completed_preparation["pool"]["image_ids"]
    rows = read_prep_stage_jsonl(data, "p08-neardup", "groups.jsonl")
    assert [row["image_id"] for row in rows] == membership
    group_of = {row["image_id"]: row["group_id"] for row in rows}
    members: dict[str, list[str]] = {}
    for row in rows:
        members.setdefault(row["group_id"], []).append(row["image_id"])
    for row in rows:
        assert row["member_count"] == len(members[row["group_id"]]), row["image_id"]
    for group_id, group_members in members.items():
        assert group_id == min(group_members)
    outline = np.load(find_prep_stage_dir(data, "p06-outline") / "outline_vectors.npy")
    full_rows = outline[:, 0, :]  # (N, d) full-image rows only (D9)
    similarities = full_rows @ full_rows.T  # (N, N)
    threshold = float(
        np.float32(completed_preparation["config"].neardup.similarity_threshold)
    )
    count = len(membership)
    for i in range(count):
        for j in range(i + 1, count):
            same_group = group_of[membership[i]] == group_of[membership[j]]
            if similarities[i, j] >= threshold:
                assert same_group, (membership[i], membership[j])
            if not same_group:
                assert similarities[i, j] < threshold, (membership[i], membership[j])


def test_scripted_near_duplicate_pair_shares_a_group(completed_preparation):
    data = completed_preparation["data"]
    membership = completed_preparation["pool"]["image_ids"]
    rows = read_prep_stage_jsonl(data, "p08-neardup", "groups.jsonl")
    group_of = {row["image_id"]: row["group_id"] for row in rows}
    count_of = {row["image_id"]: row["member_count"] for row in rows}
    dup_ids = [
        image_id for image_id in membership
        if read_fake_chunks(load_image_bytes(data, image_id)).get("embed_jitter") == "dup"
    ]
    assert len(dup_ids) == 2
    assert group_of[dup_ids[0]] == group_of[dup_ids[1]]
    for image_id in membership:
        if image_id not in dup_ids:
            assert count_of[image_id] == 1, image_id


def test_report_numbers_agree_with_the_stage_metas(completed_preparation):
    data = completed_preparation["data"]
    report = completed_preparation["report"]
    assert [entry.stage for entry in report.stages] == list(STAGE_NAMES)
    for entry in report.stages:
        meta = json.loads(
            (find_prep_stage_dir(data, entry.stage) / "meta.json").read_text()
        )
        assert entry.image_count == meta["image_count"], entry.stage
        assert entry.provider_posts == meta["provider_posts"], entry.stage
        assert entry.provider_cache_hits == meta["provider_cache_hits"], entry.stage
        assert dict(entry.counters) == meta["counters"], entry.stage
