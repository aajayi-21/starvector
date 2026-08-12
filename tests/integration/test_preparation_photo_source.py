"""Integration: a photograph-source preparation end to end on fakes.

Spec docs/specs/photo-embedding-bridge.md acceptance criterion 3: the
run wires no drawer, stage p05 records a skip, stage p06 encodes the
canonical photograph renders, and the released record loads through
the scoring context loader.
"""

import numpy as np
import pytest

from conftest import (FIXED_CLOCK, PREP_DEFAULT_SPECS,
                      build_prepared_pool_for_scoring, build_released_pool,
                      find_prep_stage_dir, make_prep_config, run_prep)
from core.canonical import sha256_hex
from pipeline.context import load_pool_index
from pool.artifacts import vector_path
from pool.preparation.stages.outline import photo_source_token


@pytest.fixture(scope="module")
def photo_preparation(tmp_path_factory):
    root = tmp_path_factory.mktemp("photo-prep")
    return build_prepared_pool_for_scoring(
        root, **{"outline.source": "photo"})


def test_the_run_completes_and_p05_records_a_skip(photo_preparation) -> None:
    report = photo_preparation["report"]
    assert report.release_label is not None
    by_stage = {entry.stage: entry for entry in report.stages}
    skip = by_stage["p05-linedraw"]
    assert skip.provider_posts == 0
    assert dict(skip.counters) == {"skipped-photo-source": 1}
    stage_dir = find_prep_stage_dir(photo_preparation["data"], "p05-linedraw")
    assert (stage_dir / "meta.json").is_file()
    assert not (stage_dir / "drawings.jsonl").exists()


def test_the_p06_vectors_sit_behind_the_photo_token(photo_preparation) -> None:
    from providers.fake.encoder import FakeImageEncoder

    data = photo_preparation["data"]
    encoder_hash = FakeImageEncoder(dimension=32).config_hash
    combined = sha256_hex(encoder_hash + photo_source_token(512))
    image_id = photo_preparation["pool"]["image_ids"][0]
    assert vector_path(data, combined, image_id).is_file()


def test_the_photo_vectors_differ_from_the_linedraw_vectors(
        photo_preparation, tmp_path) -> None:
    # One pool, the two sources: the offsets seed from the encoded
    # bytes, thus equal stacks mean p06 read the same input.
    pool = build_released_pool(tmp_path / "data", tmp_path / "pool-releases",
                               PREP_DEFAULT_SPECS)
    config = make_prep_config(pool["record_path"])
    run_prep(config, tmp_path / "data", tmp_path / "releases")
    linedraw_stack = np.load(
        find_prep_stage_dir(tmp_path / "data", "p06-outline")
        / "outline_vectors.npy")
    photo_stack = np.load(
        find_prep_stage_dir(photo_preparation["data"], "p06-outline")
        / "outline_vectors.npy")
    assert photo_stack.shape == linedraw_stack.shape
    assert not np.allclose(photo_stack, linedraw_stack)


def test_the_released_record_loads_for_scoring(photo_preparation) -> None:
    loaded = load_pool_index(photo_preparation["prep_record_path"],
                             photo_preparation["data"], dev_only=True)
    count = len(photo_preparation["pool"]["image_ids"])
    assert loaded.index.outline_vectors.shape[0] == count
    assert loaded.render.canvas_px == 512


def test_a_second_run_resumes_with_each_stage_reused(
        photo_preparation) -> None:
    from pool.preparation.config import load_preparation_config
    from pool.preparation.run import run_preparation

    config = load_preparation_config(photo_preparation["config_path"])
    report = run_preparation(
        config,
        config_path=photo_preparation["config_path"],
        data_root=photo_preparation["data"],
        releases_root=photo_preparation["releases"],
        code_version="test",
        clock=lambda: FIXED_CLOCK,
    )
    assert all(entry.skipped for entry in report.stages)


def test_an_instructed_image_encoder_forks_the_lineage(tmp_path) -> None:
    # P2c R3 with fakes: the instruction moves the image-encoder hash,
    # thus the preparation config hash, thus the artifact tree.
    from pool.preparation.config import preparation_config_hash
    from pool.preparation.run import provider_config_hashes

    plain = make_prep_config("record.json", **{"outline.source": "photo"})
    instructed = make_prep_config(
        "record.json",
        **{"outline.source": "photo",
           "providers.image_encoder.instruction_template": "sketch it"})
    assert preparation_config_hash(
        plain, provider_config_hashes(plain)
    ) != preparation_config_hash(
        instructed, provider_config_hashes(instructed))
