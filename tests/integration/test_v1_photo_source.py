"""Integration: the V1 harness on a photograph-source preparation.

Spec docs/specs/photo-embedding-bridge.md sections 6 and 10
(acceptance criterion 4): the union path runs the inserted
photographs through the canonical render with no drawer wired, the
Rule 3 guard keeps its shape, and the scripted pairs rank as the
linedraw fixture does.
"""

import pytest

from conftest import (FIXED_CLOCK, build_prepared_pool_for_scoring,
                      clone_preparation, make_scoring_config, scoring_fakes)
from validation.v1 import run_v1

# The split membership of test_v1_harness: pair 1 is the scripted
# near-duplicate of the pool fam-a pair.
NEARDUP_FAMILIES = ("solo-filler", "fam-a")
V1_COUNT = 9

INSTRUCTION = "sketch it"


def _run(clone, fakes, **config_overrides):
    overrides = {
        "validation.v1_pair_count": V1_COUNT,
        "commonness.dataset.fake_neardup_families": list(NEARDUP_FAMILIES),
        "commonness.background_count": 6,
    }
    overrides.update(config_overrides)
    config = make_scoring_config(clone["prep_record_path"], **overrides)
    return run_v1(
        config,
        data_root=clone["data"],
        records_root=clone["data"].parent / "records",
        providers=fakes,
        clock=lambda: FIXED_CLOCK,
        code_version="test",
    )


@pytest.fixture(scope="module")
def photo_run(tmp_path_factory):
    prepared = build_prepared_pool_for_scoring(
        tmp_path_factory.mktemp("v1-photo-prep"),
        **{"outline.source": "photo"})
    clone = clone_preparation(prepared,
                              tmp_path_factory.mktemp("v1-photo-run"))
    report = _run(clone, scoring_fakes(neardup_families=NEARDUP_FAMILIES))
    return {"clone": clone, "report": report}


def test_the_marker_pairs_rank_their_photographs_first(photo_run) -> None:
    # The family chunks ride the canonical render, thus the photograph
    # path keeps the scripted signal of the linedraw fixture.
    report = photo_run["report"]
    assert report.pair_count == V1_COUNT
    assert report.first_rank_fraction >= 0.8
    assert report.mean_trial_score > 0.8


def test_the_neardup_photograph_exits_with_the_pool_group(photo_run) -> None:
    # Grouping moves to photograph-embedding space and the scripted
    # near-duplicate keeps its dup epsilon, thus the union group holds.
    by_key = {row.pair_key: row for row in photo_run["report"].trials}
    assert by_key["fake://pair/0001"].decoy_count == 14
    others = [row.decoy_count for key, row in by_key.items()
              if key != "fake://pair/0001"]
    assert others == [16] * (V1_COUNT - 1)


def test_no_drawer_appears_in_the_usage_rows(photo_run) -> None:
    slots = [slot for slot, _ in photo_run["report"].usage]
    assert "line_drawer" not in slots
    assert "image_encoder" in slots


def test_the_rule_3_guard_holds_on_the_photo_path(tmp_path_factory) -> None:
    from providers.fake.encoder import FakeImageEncoder

    prepared = build_prepared_pool_for_scoring(
        tmp_path_factory.mktemp("v1-photo-guard-prep"),
        **{"outline.source": "photo"})
    clone = clone_preparation(prepared,
                              tmp_path_factory.mktemp("v1-photo-guard-run"))
    fakes = scoring_fakes(neardup_families=NEARDUP_FAMILIES)
    fakes["image_encoder"] = FakeImageEncoder(dimension=64)
    with pytest.raises(ValueError, match="Rule 3"):
        _run(clone, fakes)


def test_the_grayscale_condition_runs_and_ranks(tmp_path_factory) -> None:
    # The photo-gray condition (P2c section 9a): the family chunks
    # ride the grayscale render too, and the vectors sit behind the
    # grayscale cache token.
    from core.canonical import sha256_hex
    from pool.artifacts import vector_path
    from pool.preparation.stages.outline import photo_source_token
    from providers.fake.encoder import FakeImageEncoder

    prepared = build_prepared_pool_for_scoring(
        tmp_path_factory.mktemp("v1-gray-prep"),
        **{"outline.source": "photo", "outline.photo_render": "grayscale"})
    clone = clone_preparation(prepared,
                              tmp_path_factory.mktemp("v1-gray-run"))
    report = _run(clone, scoring_fakes(neardup_families=NEARDUP_FAMILIES))
    assert report.first_rank_fraction >= 0.8
    assert report.mean_trial_score > 0.8
    combined = sha256_hex(FakeImageEncoder(dimension=32).config_hash
                          + photo_source_token(512, grayscale=True))
    image_id = prepared["pool"]["image_ids"][0]
    assert vector_path(clone["data"], combined, image_id).is_file()


def test_the_sketch_instruction_condition_runs_and_forks(
        tmp_path_factory) -> None:
    # The photo-instructed-sym condition (P2c section 9a): the
    # sketch slot wires from the config with its instruction, the
    # scoring lineage forks, and the scripted ranking holds because
    # the fake instruction moves no vector.
    prepared = build_prepared_pool_for_scoring(
        tmp_path_factory.mktemp("v1-sym-prep"),
        **{"outline.source": "photo",
           "providers.image_encoder.instruction_template": INSTRUCTION})
    clone = clone_preparation(prepared,
                              tmp_path_factory.mktemp("v1-sym-run"))
    from providers.fake.encoder import FakeImageEncoder

    fakes = scoring_fakes(neardup_families=NEARDUP_FAMILIES)
    fakes["image_encoder"] = FakeImageEncoder(dimension=32,
                                              instruction=INSTRUCTION)
    del fakes["sketch_encoder"]   # wire from the config, instruction included
    plain = _run(clone, dict(fakes))
    sym = _run(clone, dict(fakes),
               **{"providers.sketch_encoder.instruction_template":
                  "match the photo"})
    assert sym.harness_config_hash != plain.harness_config_hash
    assert sym.first_rank_fraction >= 0.8
    assert sym.mean_trial_score > 0.8


def test_the_instructed_condition_runs_and_ranks(tmp_path_factory) -> None:
    # The photo-instructed condition end to end: the wired fake
    # carries the instruction, the hash agrees with the record, and
    # the instruction moves no fake vector, thus the ranking holds.
    from providers.fake.encoder import FakeImageEncoder

    prepared = build_prepared_pool_for_scoring(
        tmp_path_factory.mktemp("v1-inst-prep"),
        **{"outline.source": "photo",
           "providers.image_encoder.instruction_template": INSTRUCTION})
    clone = clone_preparation(prepared,
                              tmp_path_factory.mktemp("v1-inst-run"))
    fakes = scoring_fakes(neardup_families=NEARDUP_FAMILIES)
    fakes["image_encoder"] = FakeImageEncoder(dimension=32,
                                              instruction=INSTRUCTION)
    report = _run(clone, fakes)
    assert report.first_rank_fraction >= 0.8
    assert report.mean_trial_score > 0.8
