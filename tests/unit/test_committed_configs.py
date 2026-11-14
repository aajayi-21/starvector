"""The committed F1 configs parse and hold the ruled values.

Spec F1 (docs/specs/weight-freeze.md) build items B1 and B2: the
committed fit and scoring configs of the dev-wit-002 fit are pinned
here, thus a config edit that breaks the runbook fails in CI, not at
the owner's command line.
"""

import json
from pathlib import Path

import pytest

from pipeline.config import load_scoring_config
from pool.preparation.config import (load_preparation_config,
                                     preparation_config_hash)
from pool.preparation.manifest import parse_release_record
from pool.preparation.run import provider_config_hashes
from pool.preparation.stages.release import (release_label,
                                             release_preparation_version_id)
from validation import harness
from validation.fitconfig import fit_config_hash, load_fit_config


def test_the_fit_configs_parse_and_fork_on_the_tag_alone() -> None:
    base = load_fit_config(Path("configs/fit/dev-wit.json"))
    forked = load_fit_config(Path("configs/fit/dev-wit-2.json"))
    assert base.tag == "dev-wit"
    assert forked.tag == "dev-wit-2"
    assert fit_config_hash(base) != fit_config_hash(forked)
    raw_base = json.loads(Path("configs/fit/dev-wit.json").read_text())
    raw_forked = json.loads(Path("configs/fit/dev-wit-2.json").read_text())
    raw_base.pop("tag")
    raw_forked.pop("tag")
    assert raw_base == raw_forked


def test_the_source_b_config_holds_the_candidate_weight_table() -> None:
    config = load_scoring_config(Path("configs/scoring/dev-wit-b-2.json"))
    # The P4 section 17a item 4 rule: the harness config holds the
    # full candidate set while the placement build is alive.
    assert dict(config.fusion.weights) == {
        "outline": 1.0, "element": 1.0, "placement": 1.0}
    assert config.fusion.fit_record is None
    # The fit scores source-1 pairs as mixed submissions (D5).
    assert config.validation.submission_mode == "mixed"
    assert config.validation.tag == "dev-wit-b-2"
    synthetic = config.commonness.synthetic
    assert synthetic is not None
    assert synthetic.fit_config == "configs/fit/dev-wit-2.json"
    assert synthetic.count == 500
    assert config.input.preparation_record \
        == "pool/preparations/dev-wit-prep-photo-inst-2-40f06be1.json"


def test_the_service_lineage_configs_parse() -> None:
    for name in ("dev-wit-mixed-2", "dev-wit-photo-inst-sym-2"):
        config = load_scoring_config(Path(f"configs/scoring/{name}.json"))
        assert config.input.preparation_record.endswith("40f06be1.json")


def test_the_frozen_configs_hold_the_fit_winner() -> None:
    # The F1 freeze (B4): the winning table without the cut placement
    # channel, plus the fit-record label - provenance, out of the
    # scoring hash by P4 review ruling 8.
    for name in ("dev-wit-mixed-3", "dev-wit-photo-inst-sym-3"):
        config = load_scoring_config(Path(f"configs/scoring/{name}.json"))
        assert dict(config.fusion.weights) == {"element": 0.45,
                                               "outline": 0.55}
        assert config.fusion.fit_record \
            == "validation/records/fit-dev-wit-2-76056098.json"
        assert config.input.preparation_record.endswith("40f06be1.json")


def test_the_frozen_production_configs_hold_the_fit_table() -> None:
    # The production freeze (spec PP1 section 5f): the weights that V4
    # gives with no placement channel, plus the fit-record label.
    for name in ("prod-wit-mixed", "prod-wit-photo-inst-sym"):
        config = load_scoring_config(Path(f"configs/scoring/{name}.json"))
        assert dict(config.fusion.weights) == {"element": 0.5,
                                               "outline": 0.5}
        assert config.fusion.fit_record \
            == "validation/records/fit-prod-wit-43b3ca6a.json"
        assert config.input.preparation_record.endswith("fff3dddd.json")
        assert not config.report.dev_only


def test_the_production_source_b_config_keeps_the_candidate_table() -> None:
    # The fit record and the V4 record name the scoring hash of this
    # table, thus the freeze does not change the file.
    config = load_scoring_config(Path("configs/scoring/prod-wit-b.json"))
    assert dict(config.fusion.weights) == {
        "outline": 1.0, "element": 1.0, "placement": 1.0}
    assert config.fusion.fit_record is None
    frozen = json.loads(
        Path("configs/scoring/prod-wit-mixed.json").read_text())
    candidate = json.loads(
        Path("configs/scoring/prod-wit-b.json").read_text())
    for document in (frozen, candidate):
        document.pop("fusion")
        document["validation"].pop("tag")
    assert frozen == candidate


def test_the_production_service_config_names_the_frozen_config() -> None:
    from service.config import load_service_config

    service = load_service_config(Path("configs/service/prod-wit.json"))
    assert service.scoring_config == "configs/scoring/prod-wit-mixed.json"


def test_the_stitched_boundary_config_forks_on_two_fields() -> None:
    # The P5 item B8 variant: tier2_count below the dev pool count,
    # thus the tier boundary cuts on data before production. Each
    # other field stays byte-equal with the source-B config.
    config = load_scoring_config(Path("configs/scoring/dev-wit-b-2-t25.json"))
    assert config.channels.element.tier2_count == 25
    assert config.validation.tag == "dev-wit-b-2-t25"
    base = json.loads(Path("configs/scoring/dev-wit-b-2.json").read_text())
    variant = json.loads(
        Path("configs/scoring/dev-wit-b-2-t25.json").read_text())
    base["channels"]["element"].pop("tier2_count")
    variant["channels"]["element"].pop("tier2_count")
    base["validation"].pop("tag")
    variant["validation"].pop("tag")
    assert base == variant


@pytest.mark.parametrize("name", ["inst", "plain"])
def test_the_voyage_scoring_configs_name_their_precomputed_record(name: str) -> None:
    """Spec VE1 section 6: the record names are known before the run."""
    preparation_path = Path(f"configs/preparation/dev-wit-voyage-{name}.json")
    preparation = load_preparation_config(preparation_path)
    release = parse_release_record(Path(preparation.input.release_record))
    version = release_preparation_version_id(
        release.pool_version_id,
        preparation_config_hash(preparation, provider_config_hashes(preparation)))
    expected = (f"pool/preparations/"
                f"{release_label(preparation.release.tag, version)}.json")
    tags = {"inst": ("dev-wit-voyage-inst-sym", "dev-wit-voyage-inst-mixed",
                     "dev-wit-voyage-text"),
            "plain": ("dev-wit-voyage-plain-sym", "dev-wit-voyage-plain-mixed")}
    for tag in tags[name]:
        config = load_scoring_config(Path(f"configs/scoring/{tag}.json"))
        assert config.input.preparation_record == expected
        assert config.validation.tag == tag
        assert config.report.dev_only
        assert config.providers.sketch_encoder.provider == "voyage"
        assert config.providers.text_encoder.provider == "voyage"
        harness.check_outline_space(config, preparation)
        # The same frozen weights as the baseline, thus the numbers
        # compare directly.
        assert dict(config.fusion.weights) == {"element": 0.45, "outline": 0.55}


def test_the_bakeoff_cells_differ_by_the_instruction_alone() -> None:
    baseline = json.loads(
        Path("configs/preparation/dev-wit-photo-inst-2.json").read_text())
    voyage = json.loads(
        Path("configs/preparation/dev-wit-voyage-inst.json").read_text())
    assert voyage["providers"]["image_encoder"]["instruction_template"] \
        == baseline["providers"]["image_encoder"]["instruction_template"]
    plain = json.loads(
        Path("configs/preparation/dev-wit-voyage-plain.json").read_text())
    assert plain["providers"]["image_encoder"]["instruction_template"] is None
    for document in (baseline, voyage, plain):
        for slot in ("image_encoder", "text_encoder"):
            document["providers"].pop(slot)
        document["release"].pop("tag")
    assert baseline == voyage == plain
