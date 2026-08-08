"""Integration: the V1 harness on the fake prepared pool.

Invariant 10 (union grouping), the offline positive signal through the
full production path, the section 14 artifact shapes, the harness
record, the Rule 3 provider guard, and byte-equal re-runs.
"""

import shutil

import pytest

from conftest import (FIXED_CLOCK, assert_trees_identical,
                      build_prepared_pool_for_scoring, clone_preparation,
                      make_scoring_config, scoring_fakes,
                      scoring_preparation)  # noqa: F401
from core.canonical import sha256_hex
from validation.v1 import run_v1

# Pair index 1 sits in the v1 split with test-salt, and its photo is
# scripted as a near-duplicate of the pool fam-a pair. The nine v1
# members cover indices 1, 6, 7, 13, 14, 15, 16, 18, 20.
NEARDUP_FAMILIES = ("solo-filler", "fam-a")
V1_COUNT = 9


def _run(clone, **config_overrides):
    overrides = {
        "validation.v1_pair_count": V1_COUNT,
        "commonness.dataset.fake_neardup_families": list(NEARDUP_FAMILIES),
        "commonness.background_count": 6,
    }
    overrides.update(config_overrides)
    config = make_scoring_config(clone["prep_record_path"], **overrides)
    fakes = scoring_fakes(neardup_families=NEARDUP_FAMILIES)
    return run_v1(
        config,
        data_root=clone["data"],
        records_root=clone["data"].parent / "records",
        providers=fakes,
        clock=lambda: FIXED_CLOCK,
        code_version="test",
    ), fakes


@pytest.fixture(scope="module")
def v1_run(scoring_preparation, tmp_path_factory):  # noqa: F811
    clone = clone_preparation(scoring_preparation,
                              tmp_path_factory.mktemp("v1-run"))
    report, fakes = _run(clone)
    return {"clone": clone, "report": report, "fakes": fakes}


def test_the_marker_pairs_rank_their_photographs_first(v1_run) -> None:
    report = v1_run["report"]
    assert report.pair_count == V1_COUNT
    # Eight of nine pairs share a family with their photograph. The
    # scripted near-duplicate pair does not.
    assert report.first_rank_fraction >= 0.8
    assert report.top_ten_fraction >= report.first_rank_fraction
    assert report.mean_trial_score > 0.8
    assert report.reference_first < 0.1


def test_the_neardup_photograph_exits_with_the_pool_group(v1_run) -> None:
    # The union holds 8 pool images plus 9 photographs. The scripted
    # photograph joins the two-member pool fam-a group, thus its trial
    # ranks against 17 - 3 = 14 decoys. The other trials rank against 16.
    by_key = {row.pair_key: row for row in v1_run["report"].trials}
    neardup_row = by_key["fake://pair/0001"]
    assert neardup_row.decoy_count == 14
    others = [row.decoy_count for key, row in by_key.items()
              if key != "fake://pair/0001"]
    assert others == [16] * (V1_COUNT - 1)


def test_the_artifact_shapes_of_section_14_land(v1_run) -> None:
    report = v1_run["report"]
    data = v1_run["clone"]["data"]
    directory = (data / "validation" / "v1" / report.index_id[:8]
                 / report.harness_config_hash[:8])
    assert (directory / "trials.jsonl").is_file()
    assert (directory / "report.json").is_file()
    assert (directory / "meta.json").is_file()
    commonness = list((data / "commonness").glob("*/*/outline.npy"))
    assert len(commonness) == 1
    assert (commonness[0].parent / "meta.json").is_file()


def test_the_record_carries_verdict_fields_and_dev_only(v1_run) -> None:
    import json

    report = v1_run["report"]
    assert report.record_path is not None
    record = json.loads(open(report.record_path, encoding="utf-8").read())
    assert record["dev_only"] is True
    assert record["verdict"] == "pending"
    assert record["reviewer"] == ""
    assert record["harness"] == "v1"
    assert 0.0 <= record["reference_top_ten"] <= 1.0
    assert record["pair_count"] == V1_COUNT


def test_a_second_run_is_byte_identical_and_reuses_the_table(
        v1_run) -> None:
    clone = v1_run["clone"]
    reference = clone["data"].parent / "reference-data"
    shutil.copytree(clone["data"], reference)
    report, _ = _run(clone)
    assert report.usage[0] == ("sketch_encoder", (0, 0))
    assert_trees_identical(reference, clone["data"])


def test_a_provider_that_differs_from_the_record_raises(
        scoring_preparation, tmp_path) -> None:  # noqa: F811
    from providers.fake.encoder import FakeImageEncoder

    clone = clone_preparation(scoring_preparation, tmp_path)
    fakes = scoring_fakes(neardup_families=NEARDUP_FAMILIES)
    fakes["image_encoder"] = FakeImageEncoder(dimension=64)
    config = make_scoring_config(
        clone["prep_record_path"],
        **{"validation.v1_pair_count": V1_COUNT,
           "commonness.dataset.fake_neardup_families": list(NEARDUP_FAMILIES),
           "commonness.background_count": 6})
    with pytest.raises(ValueError, match="Rule 3"):
        run_v1(config, data_root=clone["data"],
               records_root=tmp_path / "records", providers=fakes,
               clock=lambda: FIXED_CLOCK)


def test_a_pair_count_above_the_split_membership_raises(
        scoring_preparation, tmp_path) -> None:  # noqa: F811
    clone = clone_preparation(scoring_preparation, tmp_path)
    config = make_scoring_config(
        clone["prep_record_path"],
        **{"validation.v1_pair_count": 10,
           "commonness.background_count": 6})
    with pytest.raises(ValueError, match="10 requested"):
        run_v1(config, data_root=clone["data"],
               records_root=tmp_path / "records",
               providers=scoring_fakes(), clock=lambda: FIXED_CLOCK)


def test_a_sketch_encoder_that_does_not_fill_the_p06_space_raises(
        scoring_preparation, tmp_path) -> None:  # noqa: F811
    clone = clone_preparation(scoring_preparation, tmp_path)
    config = make_scoring_config(
        clone["prep_record_path"],
        **{"providers.sketch_encoder.dimension": 64,
           "validation.v1_pair_count": V1_COUNT,
           "commonness.background_count": 6})
    with pytest.raises(ValueError, match="R7"):
        run_v1(config, data_root=clone["data"],
               records_root=tmp_path / "records",
               providers=scoring_fakes(dimension=64),
               clock=lambda: FIXED_CLOCK)


def test_a_filled_verdict_survives_a_re_run(scoring_preparation,
                                            tmp_path) -> None:  # noqa: F811
    import json

    clone = clone_preparation(scoring_preparation, tmp_path)
    report, _ = _run(clone)
    path = report.record_path
    record = json.loads(open(path, encoding="utf-8").read())
    record["verdict"] = "pass"
    record["reviewer"] = "ade"
    with open(path, "w", encoding="utf-8") as sink:
        json.dump(record, sink)
    second, _ = _run(clone)
    kept = json.loads(open(second.record_path, encoding="utf-8").read())
    assert kept["verdict"] == "pass"
    assert kept["reviewer"] == "ade"


def test_a_gated_sketch_stops_the_run_before_any_spend(
        scoring_preparation, tmp_path) -> None:  # noqa: F811
    clone = clone_preparation(scoring_preparation, tmp_path)
    config = make_scoring_config(
        clone["prep_record_path"],
        **{"intake.min_strokes_whole_drawing": 50,
           "validation.v1_pair_count": V1_COUNT,
           "commonness.background_count": 6})
    with pytest.raises(ValueError, match="do not clear the Layer 0 gates"):
        run_v1(config, data_root=clone["data"],
               records_root=tmp_path / "records",
               providers=scoring_fakes(), clock=lambda: FIXED_CLOCK)
    assert not (clone["data"] / "commonness").exists()


def test_a_tampered_commonness_meta_raises_on_read_back(
        scoring_preparation, tmp_path) -> None:  # noqa: F811
    import json

    clone = clone_preparation(scoring_preparation, tmp_path)
    _run(clone)
    meta_path = next((clone["data"] / "commonness").glob("*/*/meta.json"))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["index_id"] = "0" * 64
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(Exception, match="truncated-key collision"):
        _run(clone)
