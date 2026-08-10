"""Integration: the fit and the V3–V6 harnesses on fake providers.

The fixture-built pool stores vocabulary vectors from the fake text
encoder, thus a synthetic atom that names an element matches it
accurately and the generator-driven harnesses see signal offline.
"""

import json

import pytest

from conftest import (FIXED_CLOCK, build_direct_prepared_pool,
                      make_scoring_config, scoring_fakes)
from core.canonical import canonical_json_pretty
from providers.fake.generalize import FakeGeneralizer
from validation.fit import fit_split_keys, run_fit
from validation.fitconfig import load_fit_config
from validation.v3 import run_v3
from validation.v4 import run_v4
from validation.v5 import run_v5
from validation.v6 import run_v6

POOL_SIZE = 40

FIT_DOCUMENT = {
    "config_version": 1,
    "generator": {"levels": [
        {"n_atoms": 3, "generalize_p": 0.0, "n_noise": 0, "relations": 1,
         "corrupt_relation": False},
        {"n_atoms": 2, "generalize_p": 0.5, "n_noise": 1, "relations": 1,
         "corrupt_relation": True},
        {"n_atoms": 1, "generalize_p": 0.8, "n_noise": 2, "relations": 0,
         "corrupt_relation": False},
        {"n_atoms": 0, "generalize_p": 0.0, "n_noise": 3, "relations": 0,
         "corrupt_relation": False},
    ]},
    "generalize": {"provider": "fake", "model": None,
                   "instruction_template": None},
    "openrouter": {"default_model": "test/fake", "max_concurrency": 1,
                   "requests_per_second": 100.0, "timeout_seconds": 5.0,
                   "retry_limit": 0, "response_format_mode": "json_schema"},
    "fit": {"split_salt": "fit-salt", "fit_count": 3, "holdout_count": 2,
            "synthetic_count": 24, "synthetic_seed": 11,
            "line_points": 5, "simplex_step": 0.25, "signal_line": 0.65,
            "ablation_line": 0.01},
    "harness": {"v3_trials_for_each_level": 24, "v3_seed": 5,
                "v6_trial_count": 24, "v6_seed": 6,
                "v6_tier1_widths": [3, 10], "v6_tier2_widths": [1, 5]},
    "tag": "dev-test",
}


@pytest.fixture(scope="module")
def fit_setup(tmp_path_factory):
    root = tmp_path_factory.mktemp("fit-pool")
    prepared = build_direct_prepared_pool(root, POOL_SIZE)
    fit_path = root / "fit-config.json"
    fit_path.write_text(canonical_json_pretty(FIT_DOCUMENT) + "\n",
                        encoding="utf-8")
    # The harness config holds the full candidate weight set while
    # the placement experiment is alive: relation-bearing synthetics
    # activate the channel, and an active channel must have a weight.
    config = make_scoring_config(
        prepared["prep_record_path"],
        **{"fusion.weights": {"outline": 1.0, "element": 1.0,
                              "placement": 1.0},
           "commonness.dataset.fake_pair_count": 24,
           "commonness.background_count": 12,
           "commonness.synthetic": {"fit_config": str(fit_path),
                                    "count": 6, "seed": 17},
           "validation.submission_mode": "mixed",
           "validation.v1_pair_count": 4,
           "validation.v2_trial_count": 4})
    fit_config = load_fit_config(fit_path)
    providers = {**scoring_fakes(pair_count=24),
                 "generalizer": FakeGeneralizer()}
    return {"prepared": prepared, "config": config,
            "fit_config": fit_config, "providers": providers,
            "records": root / "records"}


def _run_fit(setup):
    return run_fit(setup["config"], setup["fit_config"],
                   data_root=setup["prepared"]["data"],
                   records_root=setup["records"],
                   providers=setup["providers"],
                   clock=lambda: FIXED_CLOCK, code_version="test")


def test_the_fit_split_is_disjoint_from_the_gate_pairs(fit_setup) -> None:
    source = fit_setup["providers"]["sketch_pairs"]
    keys = [pair.pair_key for pair in source.iter_pairs()]
    fit_keys, holdout_keys = fit_split_keys(keys, fit_setup["config"],
                                            fit_setup["fit_config"])
    assert len(fit_keys) == 3 and len(holdout_keys) == 2
    assert not set(fit_keys) & set(holdout_keys)
    from validation.splits import select_keys

    gates = select_keys(keys, "test-salt",
                        fit_setup["config"].commonness.split_fractions,
                        "v1", 4)
    assert not set(gates) & (set(fit_keys) | set(holdout_keys))


def test_the_fit_writes_a_record_with_the_full_curve(fit_setup) -> None:
    content = _run_fit(fit_setup)
    assert content["verdict"] == "pending"
    assert len(content["curve"]["line"]) == 5
    assert content["placement_signal"] is not None
    # The scripted relations come from the box geometry, thus the
    # placement-only mean on strong holdout synthetics beats the
    # signal line and the simplex path runs.
    assert content["placement_signal"] > 0.65
    assert content["placement_alive"] is True
    assert content["objective_basis"] == "mixed"
    assert 0.0 <= content["holdout_objective"] <= 1.0
    record = json.loads(
        open(content["record_path"], encoding="utf-8").read())
    assert record["harness"] == "fit"
    assert record["freeze_blocked"] == record["endpoint"]


def test_the_simplex_evaluates_each_point(fit_setup) -> None:
    # The review found the pure-placement vertex crashed the fit:
    # source 1 pairs hold no relation, thus the vertex reads no
    # source 1 trial and its mean counts 0.5 for each one (ruling
    # 2026-08-10). The full 0.25-step simplex must complete.
    content = _run_fit(fit_setup)
    simplex = content["curve"]["simplex"]
    assert len(simplex) == 15
    vertex = next(row for row in simplex
                  if row["weights"] == {"element": 0.0, "outline": 0.0,
                                        "placement": 1.0})
    assert 0.0 <= vertex["objective"] <= 1.0
    assert vertex["readable_trials"]["source1"] == 0
    assert vertex["readable_trials"]["source2"] > 0
    for row in simplex:
        assert row["objective"] is not None


def test_the_fit_reproduces_byte_for_byte(fit_setup) -> None:
    first = _run_fit(fit_setup)
    second = _run_fit(fit_setup)
    assert first["curve"] == second["curve"]
    assert first["winner"] == second["winner"]


def test_v3_sees_a_monotone_curve_with_the_control_at_half(
        fit_setup) -> None:
    content = run_v3(fit_setup["config"], fit_setup["fit_config"],
                     data_root=fit_setup["prepared"]["data"],
                     records_root=fit_setup["records"],
                     providers=fit_setup["providers"],
                     clock=lambda: FIXED_CLOCK, code_version="test")
    means = [row["mean_p"] for row in content["levels"]]
    assert content["monotone"], means
    assert content["control_at_half"], means
    assert means[0] > 0.9
    record = json.loads(
        open(content["record_path"], encoding="utf-8").read())
    assert record["verdict"] == "pending"
    assert record["fusion_weights_fitted"] is False


def test_v4_reports_a_cost_for_each_channel(fit_setup) -> None:
    content = run_v4(fit_setup["config"], fit_setup["fit_config"],
                     data_root=fit_setup["prepared"]["data"],
                     records_root=fit_setup["records"],
                     providers=fit_setup["providers"],
                     clock=lambda: FIXED_CLOCK, code_version="test")
    removed = {row["removed"] for row in content["ablations"]}
    assert removed == set(content["channel_set"])
    assert "element" in removed
    # Placement is alive on the fixture, thus its ablation row — the
    # D8 contribution half — must be in the table, measured on the
    # same mixed basis as the full set (ruling 2026-08-10).
    assert "placement" in removed
    assert content["objective_basis"] == "mixed"
    assert isinstance(content["placement_earns_its_place"], bool)
    element_cost = next(row["cost"] for row in content["ablations"]
                        if row["removed"] == "element")
    # The element channel carries the offline signal: removal cannot
    # help. The fake path saturates near 1.0, thus the cost can sit at
    # zero here — the live run is where the delta means something.
    assert element_cost >= 0.0


def test_v5_reports_concentration_and_slopes(fit_setup) -> None:
    content = run_v5(fit_setup["config"], fit_setup["fit_config"],
                     data_root=fit_setup["prepared"]["data"],
                     records_root=fit_setup["records"],
                     providers=fit_setup["providers"],
                     clock=lambda: FIXED_CLOCK, code_version="test")
    assert content["background_scored"] > 0
    assert content["slope_trial_count"] == 4
    assert set(content["commonness_slopes"]) \
        <= {"outline", "element", "placement"}
    for slope in content["commonness_slopes"].values():
        assert -1.0 <= slope <= 1.0


def test_v6_recall_grows_with_the_width(fit_setup) -> None:
    content = run_v6(fit_setup["config"], fit_setup["fit_config"],
                     data_root=fit_setup["prepared"]["data"],
                     records_root=fit_setup["records"],
                     providers=fit_setup["providers"],
                     clock=lambda: FIXED_CLOCK, code_version="test")
    tier1 = content["tier1_recall"]
    assert tier1["3"] <= tier1["10"]
    tier2 = content["tier2_recall"]
    assert tier2["1"] <= tier2["5"]
    # Levels 0 and 1 hold the named elements, thus the accurate head
    # finds most targets on the fake path.
    assert tier2["5"] > 0.5
