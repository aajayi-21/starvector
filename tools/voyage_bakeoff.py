"""The Voyage bake-off as one command, for the owner to run.

Spec: docs/specs/voyage-encoder.md section 8. This tool runs steps 2 to
6 of that runbook in sequence: the smoke check, the two Voyage
preparations, the near-duplicate calibration, the V2 and V1 gates, and
the paired tables. Each step prints its numbers, and a text file gets
the same output. The tool picks no threshold, writes no config, and gives
no verdict (spec VE1 sections 5 and 9).

Each vector goes to the cache, thus a second run after a stop does the
complete steps again from the cache with no new spend. The keys come
from the environment and are not printed.
"""

import argparse
import contextlib
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple, TextIO

DATA_ROOT = Path("data")
RECORDS_ROOT = Path("validation/records")
RELEASES_ROOT = Path("pool/preparations")
DEFAULT_LOG = DATA_ROOT / "validation" / "bakeoff" / "voyage-bakeoff.log"

KEY_NAMES: tuple[str, ...] = ("VOYAGE_API_KEY", "OPENROUTER_API_KEY")
LIMIT_NAMES: tuple[str, ...] = ("VOYAGE_REQUESTS_PER_MINUTE",
                                "VOYAGE_TOKENS_PER_MINUTE")

_PREPARATION = Path("configs/preparation")
_CURATION = Path("configs/curation")
_SCORING = Path("configs/scoring")


class Table(NamedTuple):
    """One paired table of spec VE1 section 8, step 6.

    Each field names a scoring config. v2 holds candidate configs: the
    adoption rule reads the V2 record of each one for this table.
    """

    name: str
    baseline: Path
    candidate: Path
    v2: tuple[Path, ...]


class Plan(NamedTuple):
    """The configs of one bake-off, in the sequence in which they run.

    calibrations holds pairs of a preparation config and a curation
    config. The preparation of the first config in a pair is complete
    before its calibration starts.
    """

    preparations: tuple[Path, ...]
    calibrations: tuple[tuple[Path, Path], ...]
    v2_configs: tuple[Path, ...]
    v1_configs: tuple[Path, ...]
    tables: tuple[Table, ...]


class Steps(NamedTuple):
    """The work of each step, as functions that print their numbers.

    prepare gives the count of p08 groups with two or more members. v2
    and v1 give the path of the harness record. table gets the baseline
    V1 record, the candidate V1 record, and the candidate V2 records.
    """

    smoke: Callable[[], None]
    prepare: Callable[[Path], int]
    calibrate: Callable[[Path, Path], None]
    v2: Callable[[Path], Path]
    v1: Callable[[Path], Path]
    table: Callable[[Path, Path, Sequence[Path]], None]


class Summary(NamedTuple):
    """What one complete run made, for the last lines of the report."""

    grouped: Mapping[Path, int]
    v2_records: Mapping[Path, Path]
    v1_records: Mapping[Path, Path]


# The cells and the tables of spec VE1 sections 6 and 8. The sketch
# baseline also runs here, where the spec uses the record on file. Its
# vectors are in the cache, and the run shows that the code of this day
# gives the rows of that record again.
VE1_PLAN = Plan(
    preparations=(
        _PREPARATION / "dev-wit-voyage-inst.json",
        _PREPARATION / "dev-wit-voyage-plain.json",
    ),
    calibrations=(
        (_PREPARATION / "dev-wit-voyage-inst.json",
         _CURATION / "dev-wit-voyage.json"),
        (_PREPARATION / "dev-wit-photo-inst-2.json",
         _CURATION / "dev-wit-2.json"),
    ),
    v2_configs=(
        _SCORING / "dev-wit-voyage-inst-sym.json",
        _SCORING / "dev-wit-voyage-inst-mixed.json",
        _SCORING / "dev-wit-voyage-plain-sym.json",
        _SCORING / "dev-wit-voyage-plain-mixed.json",
        _SCORING / "dev-wit-voyage-text.json",
    ),
    v1_configs=(
        _SCORING / "dev-wit-voyage-inst-sym.json",
        _SCORING / "dev-wit-voyage-inst-mixed.json",
        _SCORING / "dev-wit-voyage-plain-sym.json",
        _SCORING / "dev-wit-voyage-plain-mixed.json",
        _SCORING / "dev-wit-voyage-text.json",
        _SCORING / "dev-wit-photo-inst-sym-3.json",
        _SCORING / "dev-wit-text-3.json",
        _SCORING / "dev-wit-mixed-3.json",
    ),
    tables=(
        Table("Image and sketch slots, with instructions",
              _SCORING / "dev-wit-photo-inst-sym-3.json",
              _SCORING / "dev-wit-voyage-inst-sym.json",
              (_SCORING / "dev-wit-voyage-inst-sym.json",
               _SCORING / "dev-wit-voyage-inst-mixed.json")),
        Table("Image and sketch slots, no instructions",
              _SCORING / "dev-wit-photo-inst-sym-3.json",
              _SCORING / "dev-wit-voyage-plain-sym.json",
              (_SCORING / "dev-wit-voyage-plain-sym.json",
               _SCORING / "dev-wit-voyage-plain-mixed.json")),
        Table("Text slot",
              _SCORING / "dev-wit-text-3.json",
              _SCORING / "dev-wit-voyage-text.json",
              (_SCORING / "dev-wit-voyage-text.json",)),
        Table("Mixed, for the record",
              _SCORING / "dev-wit-mixed-3.json",
              _SCORING / "dev-wit-voyage-inst-mixed.json",
              ()),
    ),
)


def plan_problems(plan: Plan) -> list[str]:
    """The table entries that no gate of the plan makes a record for."""
    problems: list[str] = []
    for table in plan.tables:
        for config in (table.baseline, table.candidate):
            if config not in plan.v1_configs:
                problems.append(f"{table.name}: no V1 run of {config}")
        for config in table.v2:
            if config not in plan.v2_configs:
                problems.append(f"{table.name}: no V2 run of {config}")
    return problems


def missing_keys(environment: Mapping[str, str]) -> list[str]:
    """The key names with no value in the environment. No value is read out."""
    return [name for name in KEY_NAMES if not environment.get(name)]


def multi_member_groups(counters: Sequence[tuple[str, int]]) -> int:
    """The p08 groups with two or more members.

    counters is the p08 histogram: each name is `members-<count>` and
    each value is the number of groups with that member count.
    """
    total = 0
    for name, group_count in counters:
        prefix, _, member_count = name.partition("-")
        if prefix != "members" or not member_count.isdigit():
            raise ValueError(f"p08 gave a counter that is not a histogram "
                             f"entry: {name!r}")
        if int(member_count) >= 2:
            total += group_count
    return total


def predicted_preparation_record(config_path: Path, releases_root: Path) -> Path:
    """The record path that the preparation of this config writes.

    The preparation version comes from the pool version and the config
    hash alone, thus the network is not necessary.
    """
    from pool.preparation import manifest as mf
    from pool.preparation.config import (load_preparation_config,
                                         preparation_config_hash)
    from pool.preparation.run import provider_config_hashes
    from pool.preparation.stages import release

    config = load_preparation_config(config_path)
    pool_record = mf.parse_release_record(Path(config.input.release_record))
    version = release.release_preparation_version_id(
        pool_record.pool_version_id,
        preparation_config_hash(config, provider_config_hashes(config)))
    label = release.release_label(config.release.tag, version)
    return releases_root / f"{label}.json"


def record_problems(plan: Plan, releases_root: Path) -> list[str]:
    """The scoring configs with a preparation record that this run cannot give.

    A record is available when it is on the disk, or when a preparation
    of the plan writes it. A different name stops V1 after the
    preparation spend, thus this check runs first.
    """
    from pipeline.config import load_scoring_config

    predicted = {predicted_preparation_record(config, releases_root)
                 for config in plan.preparations}
    problems: list[str] = []
    for config_path in dict.fromkeys(plan.v2_configs + plan.v1_configs):
        record = Path(load_scoring_config(config_path).input.preparation_record)
        if record not in predicted and not record.is_file():
            problems.append(
                f"{config_path}: the preparation record {record} is not on "
                "the disk, and no preparation of this run writes it")
    return problems


def preflight(plan: Plan, environment: Mapping[str, str],
              releases_root: Path) -> list[str]:
    """Each problem that stops the run before it uses the network. Empty is good."""
    problems = plan_problems(plan)
    problems.extend(f"{name} is not in the environment"
                    for name in missing_keys(environment))
    paths = (plan.preparations + plan.v2_configs + plan.v1_configs
             + tuple(path for pair in plan.calibrations for path in pair))
    absent = [path for path in dict.fromkeys(paths) if not path.is_file()]
    problems.extend(f"{path}: no such config file" for path in absent)
    if not absent:
        problems.extend(record_problems(plan, releases_root))
    return problems


def format_preflight(problems: Sequence[str],
                     environment: Mapping[str, str]) -> str:
    """The preflight lines. A key shows as set or not set, and its value does not show."""
    lines = [f"{name}: {'set' if environment.get(name) else 'NOT SET'}"
             for name in KEY_NAMES]
    lines.extend(
        f"{name}: {environment.get(name) or 'not set, the tier 1 default applies'}"
        for name in LIMIT_NAMES)
    lines.extend(f"PROBLEM  {problem}" for problem in problems)
    lines.append("preflight: no problem found" if not problems else
                 f"preflight: {len(problems)} problems, no step ran")
    return "\n".join(lines)


@contextlib.contextmanager
def _step(name: str, clock: Callable[[], float]) -> Iterator[None]:
    """Print the name of a step, then its elapsed time or where it stopped."""
    print(f"\n=== {name} ===", flush=True)
    start = clock()
    try:
        yield
    except BaseException:
        print(f"*** stopped in: {name}", flush=True)
        raise
    print(f"--- {name}: {clock() - start:.0f} s", flush=True)


def run_plan(plan: Plan, steps: Steps,
             clock: Callable[[], float] = time.monotonic) -> Summary:
    """Run each step of the plan in sequence. An error stops the run.

    The tables run last, because each table reads the records of the
    gates. No step reads the output of a table.
    """
    with _step("smoke", clock):
        steps.smoke()
    grouped: dict[Path, int] = {}
    for config in plan.preparations:
        with _step(f"preparation {config.stem}", clock):
            grouped[config] = steps.prepare(config)
            print(f"p08 groups with two or more members: {grouped[config]}")
    for preparation, curation in plan.calibrations:
        with _step(f"calibration {preparation.stem}", clock):
            steps.calibrate(preparation, curation)
    v2_records: dict[Path, Path] = {}
    for config in plan.v2_configs:
        with _step(f"V2 {config.stem}", clock):
            v2_records[config] = steps.v2(config)
    v1_records: dict[Path, Path] = {}
    for config in plan.v1_configs:
        with _step(f"V1 {config.stem}", clock):
            v1_records[config] = steps.v1(config)
    for table in plan.tables:
        with _step(f"table: {table.name}", clock):
            steps.table(v1_records[table.baseline], v1_records[table.candidate],
                        [v2_records[config] for config in table.v2])
    return Summary(grouped=grouped, v2_records=v2_records,
                   v1_records=v1_records)


def format_summary(summary: Summary) -> str:
    """The last lines: the p08 groups, the records, and what comes next."""
    lines = ["", "=== summary ==="]
    for config, count in summary.grouped.items():
        lines.append(f"{config.stem}: p08 groups with two or more members: "
                     f"{count}")
    if any(summary.grouped.values()):
        lines.append("p08 grouped images in the Voyage space: the numbers "
                     "wait for the threshold ruling (spec VE1 section 5).")
    lines.extend(f"V1 record  {path}" for path in summary.v1_records.values())
    lines.extend(f"V2 record  {path}" for path in summary.v2_records.values())
    lines.append("A new record has a pending verdict field. The verdict of "
                 "the bake-off is the owner's (spec VE1 section 9).")
    return "\n".join(lines)


def _code_version() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


def _checked_exit(tool: str, exit_code: int) -> None:
    if exit_code != 0:
        raise RuntimeError(f"{tool} ended with exit code {exit_code}")


def _smoke() -> None:
    from tools import voyage_smoke

    _checked_exit("tools.voyage_smoke", voyage_smoke.main([]))


def _prepare(config_path: Path) -> int:
    from pool.preparation.config import load_preparation_config
    from pool.preparation.run import format_report, run_preparation

    report = run_preparation(
        load_preparation_config(config_path), config_path=config_path,
        data_root=DATA_ROOT, releases_root=RELEASES_ROOT,
        code_version=_code_version())
    print(format_report(report))
    if report.release_record_path is None:
        raise RuntimeError(f"{config_path}: the preparation wrote no record")
    expected = predicted_preparation_record(config_path, RELEASES_ROOT)
    if Path(report.release_record_path) != expected:
        raise RuntimeError(
            f"{config_path}: the preparation wrote "
            f"{report.release_record_path}, and the preflight gave {expected}")
    for entry in report.stages:
        if entry.stage == "p08-neardup":
            return multi_member_groups(entry.counters)
    raise RuntimeError(f"{config_path}: the report has no p08-neardup stage")


def _calibrate(preparation: Path, curation: Path) -> None:
    from validation import neardup_calibration

    _checked_exit("validation.neardup_calibration", neardup_calibration.main([
        "--config", str(preparation), "--curation-config", str(curation),
        "--data-root", str(DATA_ROOT), "--records-root", str(RECORDS_ROOT)]))


def _record_of(config_path: Path, record_path: str | None) -> Path:
    if record_path is None:
        raise RuntimeError(
            f"{config_path}: the run wrote no record, because it did not "
            "complete the trial count of the config")
    return Path(record_path)


def _v2(config_path: Path) -> Path:
    from pipeline.config import load_scoring_config
    from validation import v2

    report = v2.run_v2(load_scoring_config(config_path), data_root=DATA_ROOT,
                       records_root=RECORDS_ROOT)
    print(v2.format_report(report))
    return _record_of(config_path, report.record_path)


def _v1(config_path: Path) -> Path:
    from pipeline.config import load_scoring_config
    from validation import v1

    report = v1.run_v1(load_scoring_config(config_path), data_root=DATA_ROOT,
                       records_root=RECORDS_ROOT)
    print(v1.format_report(report))
    return _record_of(config_path, report.record_path)


def _table(baseline: Path, candidate: Path, v2_records: Sequence[Path]) -> None:
    from validation import bakeoff

    arguments = ["--baseline", str(baseline), "--candidate", str(candidate),
                 "--data-root", str(DATA_ROOT)]
    for record in v2_records:
        arguments.extend(("--v2", str(record)))
    _checked_exit("validation.bakeoff", bakeoff.main(arguments))


LIVE_STEPS = Steps(smoke=_smoke, prepare=_prepare, calibrate=_calibrate,
                   v2=_v2, v1=_v1, table=_table)


class _Tee:
    """A text stream that writes each string to two streams."""

    def __init__(self, first: TextIO, second: TextIO) -> None:
        self._streams = (first, second)

    def write(self, text: str) -> int:
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def main(argv: list[str] | None = None, *, plan: Plan = VE1_PLAN,
         steps: Steps = LIVE_STEPS,
         environment: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.voyage_bakeoff")
    parser.add_argument("--check", action="store_true",
                        help="do the preflight and stop, with no network call")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG,
                        help="the file that gets a copy of the output")
    arguments = parser.parse_args(argv)
    environment = os.environ if environment is None else environment

    problems = preflight(plan, environment, RELEASES_ROOT)
    preflight_text = format_preflight(problems, environment)
    print(preflight_text)
    if problems:
        return 2
    if arguments.check:
        return 0

    arguments.log.parent.mkdir(parents=True, exist_ok=True)
    with arguments.log.open("w", encoding="utf-8") as log, \
            contextlib.redirect_stdout(_Tee(sys.stdout, log)):
        log.write(preflight_text + "\n")
        summary = run_plan(plan, steps)
        print(format_summary(summary))
    print(f"log  {arguments.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
