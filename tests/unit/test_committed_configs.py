"""The committed F1 configs parse and hold the ruled values.

Spec F1 (docs/specs/weight-freeze.md) build items B1 and B2: the
committed fit and scoring configs of the dev-wit-002 fit are pinned
here, thus a config edit that breaks the runbook fails in CI, not at
the owner's command line.
"""

import json
from pathlib import Path

from pipeline.config import load_scoring_config
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
