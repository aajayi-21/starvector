"""The one-command bake-off runner, offline, with recorded steps."""

import json
from pathlib import Path

import pytest

from tools import voyage_bakeoff as runner

KEYS = {"VOYAGE_API_KEY": "voyage-secret-value",
        "OPENROUTER_API_KEY": "openrouter-secret-value"}
RELEASES = Path("pool/preparations")


def recorded_steps(calls: list[tuple], grouped: int = 0,
                   stop_at: str | None = None) -> runner.Steps:
    """Steps that record each use, write no file, and do not use the network."""

    def note(name: str, *arguments) -> None:
        calls.append((name, *arguments))
        if stop_at == name:
            raise RuntimeError(f"scripted stop in {name}")

    def prepare(config: Path) -> int:
        note("prepare", config)
        return grouped

    def gate(name: str):
        def run(config: Path) -> Path:
            note(name, config)
            return Path(f"records/{name}-{config.stem}.json")
        return run

    return runner.Steps(
        smoke=lambda: note("smoke"),
        prepare=prepare,
        calibrate=lambda preparation, curation: note(
            "calibrate", preparation, curation),
        v2=gate("v2"),
        v1=gate("v1"),
        table=lambda baseline, candidate, v2_records: note(
            "table", baseline, candidate, tuple(v2_records)),
    )


def test_the_plan_is_the_runbook_of_the_spec() -> None:
    plan = runner.VE1_PLAN
    assert runner.plan_problems(plan) == []
    assert [table.name for table in plan.tables] == [
        "Image and sketch slots, with instructions",
        "Image and sketch slots, no instructions",
        "Text slot",
        "Mixed, for the record",
    ]
    # Rule 3 reads the sketch mode and the mixed mode for a sketch
    # table, the text mode for the text table, and no mode for mixed.
    assert [[path.stem for path in table.v2] for table in plan.tables] == [
        ["dev-wit-voyage-inst-sym", "dev-wit-voyage-inst-mixed"],
        ["dev-wit-voyage-plain-sym", "dev-wit-voyage-plain-mixed"],
        ["dev-wit-voyage-text"],
        [],
    ]
    assert [table.baseline.stem for table in plan.tables] == [
        "dev-wit-photo-inst-sym-3", "dev-wit-photo-inst-sym-3",
        "dev-wit-text-3", "dev-wit-mixed-3"]
    # Each new scoring config gets the two gates (spec VE1 section 8).
    voyage = [path for path in plan.v1_configs if "voyage" in path.stem]
    assert tuple(voyage) == plan.v2_configs
    assert len(plan.v2_configs) == 5


def test_a_table_with_no_gate_run_is_a_problem() -> None:
    plan = runner.Plan(
        preparations=(), calibrations=(), v2_configs=(),
        v1_configs=(Path("a.json"),),
        tables=(runner.Table("t", Path("a.json"), Path("b.json"),
                             (Path("b.json"),)),))
    assert runner.plan_problems(plan) == [
        "t: no V1 run of b.json", "t: no V2 run of b.json"]


def test_an_empty_key_is_a_missing_key() -> None:
    assert runner.missing_keys(KEYS) == []
    assert runner.missing_keys({"VOYAGE_API_KEY": "x"}) == ["OPENROUTER_API_KEY"]
    assert runner.missing_keys({"VOYAGE_API_KEY": "", "OPENROUTER_API_KEY": "x"}) \
        == ["VOYAGE_API_KEY"]


def test_the_preflight_text_holds_no_key_value() -> None:
    text = runner.format_preflight([], KEYS)
    assert "VOYAGE_API_KEY: set" in text
    assert "OPENROUTER_API_KEY: set" in text
    for value in KEYS.values():
        assert value not in text


def test_the_group_count_reads_the_p08_histogram() -> None:
    assert runner.multi_member_groups((("members-1", 204),)) == 0
    assert runner.multi_member_groups(
        (("members-1", 196), ("members-2", 3), ("members-3", 1))) == 4
    with pytest.raises(ValueError, match="not a histogram"):
        runner.multi_member_groups((("images", 204),))


def test_the_committed_configs_name_the_predicted_records() -> None:
    # The Voyage preparation records are not on the disk before the
    # run. Each scoring config must name the record that its
    # preparation writes, or V1 stops after the preparation spend.
    plan = runner.VE1_PLAN
    predicted = [runner.predicted_preparation_record(config, RELEASES).name
                 for config in plan.preparations]
    assert predicted == ["dev-wit-prep-voyage-inst-81bfdcff.json",
                         "dev-wit-prep-voyage-plain-c6be4754.json"]
    assert runner.record_problems(plan, RELEASES) == []
    assert runner.preflight(plan, KEYS, RELEASES) == []


def test_a_scoring_config_with_a_different_record_is_a_problem(tmp_path) -> None:
    document = json.loads(
        Path("configs/scoring/dev-wit-voyage-text.json").read_text())
    document["input"]["preparation_record"] = \
        "pool/preparations/dev-wit-prep-voyage-inst-00000000.json"
    moved = tmp_path / "moved.json"
    moved.write_text(json.dumps(document))
    plan = runner.VE1_PLAN._replace(v2_configs=(moved,), v1_configs=(),
                                    tables=())
    problems = runner.record_problems(plan, RELEASES)
    assert len(problems) == 1
    assert "dev-wit-prep-voyage-inst-00000000.json" in problems[0]


def test_a_missing_config_file_is_a_problem(tmp_path) -> None:
    plan = runner.VE1_PLAN._replace(
        preparations=(tmp_path / "absent.json",))
    problems = runner.preflight(plan, KEYS, RELEASES)
    assert problems == [f"{tmp_path / 'absent.json'}: no such config file"]


def test_the_steps_run_in_sequence_and_each_table_gets_its_records() -> None:
    calls: list[tuple] = []
    plan = runner.VE1_PLAN
    summary = runner.run_plan(plan, recorded_steps(calls), clock=lambda: 0.0)

    names = [call[0] for call in calls]
    assert names == (["smoke"] + ["prepare"] * 2 + ["calibrate"] * 2
                     + ["v2"] * 5 + ["v1"] * 8 + ["table"] * 4)
    assert [call[1] for call in calls if call[0] == "prepare"] \
        == list(plan.preparations)
    assert [call[1:] for call in calls if call[0] == "calibrate"] \
        == list(plan.calibrations)

    tables = [call[1:] for call in calls if call[0] == "table"]
    assert tables[0] == (
        Path("records/v1-dev-wit-photo-inst-sym-3.json"),
        Path("records/v1-dev-wit-voyage-inst-sym.json"),
        (Path("records/v2-dev-wit-voyage-inst-sym.json"),
         Path("records/v2-dev-wit-voyage-inst-mixed.json")))
    assert tables[2] == (
        Path("records/v1-dev-wit-text-3.json"),
        Path("records/v1-dev-wit-voyage-text.json"),
        (Path("records/v2-dev-wit-voyage-text.json"),))
    assert tables[3] == (
        Path("records/v1-dev-wit-mixed-3.json"),
        Path("records/v1-dev-wit-voyage-inst-mixed.json"),
        ())
    assert len(summary.v1_records) == 8
    assert len(summary.v2_records) == 5
    assert set(summary.grouped.values()) == {0}


def test_an_error_stops_the_run_and_the_output_names_the_step(capsys) -> None:
    calls: list[tuple] = []
    with pytest.raises(RuntimeError, match="scripted stop in v2"):
        runner.run_plan(runner.VE1_PLAN, recorded_steps(calls, stop_at="v2"),
                        clock=lambda: 0.0)
    assert [call[0] for call in calls].count("v2") == 1
    assert "v1" not in [call[0] for call in calls]
    assert "*** stopped in: V2 dev-wit-voyage-inst-sym" in capsys.readouterr().out


def test_the_summary_tells_of_grouped_images() -> None:
    calls: list[tuple] = []
    clean = runner.run_plan(runner.VE1_PLAN, recorded_steps(calls),
                            clock=lambda: 0.0)
    assert "threshold ruling" not in runner.format_summary(clean)
    grouped = runner.run_plan(runner.VE1_PLAN, recorded_steps(calls, grouped=2),
                              clock=lambda: 0.0)
    text = runner.format_summary(grouped)
    assert "dev-wit-voyage-inst: p08 groups with two or more members: 2" in text
    assert "wait for the threshold ruling" in text


def test_a_missing_key_runs_no_step(tmp_path, capsys) -> None:
    calls: list[tuple] = []
    log = tmp_path / "run.log"
    code = runner.main(["--log", str(log)], steps=recorded_steps(calls),
                       environment={"VOYAGE_API_KEY": "x"})
    assert code == 2
    assert calls == []
    assert not log.exists()
    assert "OPENROUTER_API_KEY is not in the environment" in capsys.readouterr().out


def test_the_check_option_runs_no_step(tmp_path) -> None:
    calls: list[tuple] = []
    log = tmp_path / "run.log"
    code = runner.main(["--check", "--log", str(log)],
                       steps=recorded_steps(calls), environment=KEYS)
    assert code == 0
    assert calls == []
    assert not log.exists()


def test_a_complete_run_writes_the_log_with_no_key_value(tmp_path, capsys) -> None:
    calls: list[tuple] = []
    log = tmp_path / "logs" / "run.log"
    code = runner.main(["--log", str(log)], steps=recorded_steps(calls),
                       environment=KEYS)
    assert code == 0
    assert len(calls) == 22
    text = log.read_text(encoding="utf-8")
    shown = capsys.readouterr().out
    for part in ("preflight: no problem found", "=== smoke ===",
                 "=== table: Text slot ===", "=== summary ===",
                 "V1 record  records/v1-dev-wit-voyage-text.json"):
        assert part in text
        assert part in shown
    assert shown.count("preflight: no problem found") == 1
    for value in KEYS.values():
        assert value not in text
        assert value not in shown
