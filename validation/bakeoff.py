"""The paired table of one encoder against a different encoder (spec VE1).

Spec: docs/specs/voyage-encoder.md section 6. It reads the pair rows
of two V1 runs on the same sketch pairs, and the KS values of the
candidate's V2 runs. It reports the rule lines and changes no config.
The verdict is the owner's. No live player trial enters this tool
(I6): V1 pairs have a known correspondence by construction.

The tool refuses evidence that is not the candidate's: two V1 runs of
different submission modes, a V2 record of a different preparation,
and a record with trial rows that moved after the record. It
reports the decoy counts of the two runs, because V1 groups
near-duplicates in each encoder space (Rule 3), and a run with fewer
decoys has an easier first rank.
"""

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

from validation import harness

# The two numeric lines of the adoption rule (spec VE1 section 6).
FIRST_RANK_FLOOR = 0.63
SIGNIFICANCE_LINE = 0.05
_TOP_TEN = 10

# The V2 modes rule 3 reads for each V1 mode (spec VE1 section 6). The
# image and sketch slots want the sketch mode and the mixed mode. The
# text slot wants its own mode. No rule reads a mixed V1 run.
V2_MODES_FOR: dict[str, tuple[str, ...]] = {
    "sketch": ("sketch", "mixed"),
    "text": ("text",),
    "mixed": (),
}


class PairedTable(NamedTuple):
    """First-rank trials of two runs on one pair set.

    candidate_only counts the pairs the candidate placed first and the
    baseline did not, and baseline_only counts the opposite pairs.
    """

    pair_count: int
    baseline_first: float
    candidate_first: float
    baseline_top_ten: float
    candidate_top_ten: float
    candidate_only: int
    baseline_only: int
    mcnemar_p: float


class RuleLine(NamedTuple):
    """One line of the adoption rule, with its numbers."""

    name: str
    holds: bool
    detail: str


class DecoyParity(NamedTuple):
    """The decoy counts of two V1 runs, pair by pair.

    V1 groups near-duplicates across the pool and the inserted
    photographs in the encoder space of each run, and the target's group
    is not in its decoy set (Rule 3). Two encoders can thus give one
    pair two different decoy sets. candidate_fewer counts the pairs
    where the candidate holds fewer decoys than the baseline, and
    candidate_more counts the opposite pairs.

    conservative_first is the candidate's first-rank fraction with each
    first rank on a candidate_fewer pair counted as not first. A decoy
    that is not in the set could have a score above the target, thus
    this is the lowest value the equal-decoy fraction can have.

    Equal counts do not show equal sets. The trial rows hold the counts
    alone, and this is the evidence the rows give.
    """

    baseline_counts: tuple[tuple[int, int], ...]
    candidate_counts: tuple[tuple[int, int], ...]
    candidate_fewer: int
    candidate_more: int
    conservative_first: float


def mcnemar_exact_p(candidate_only: int, baseline_only: int) -> float:
    """The two-sided McNemar p: a binomial test on discordant pairs.

    With no discordant pair the two runs agree, and p is 1. The binomial
    sum is the correct one at the small counts that 200 pairs can give.
    """
    discordant = candidate_only + baseline_only
    if discordant == 0:
        return 1.0
    smaller = min(candidate_only, baseline_only)
    tail = sum(math.comb(discordant, k) for k in range(smaller + 1))
    return min(1.0, 2.0 * tail / 2.0 ** discordant)


def paired_table(baseline: Sequence[Mapping[str, object]],
                 candidate: Sequence[Mapping[str, object]]) -> PairedTable:
    """Pair two V1 trial sets by pair_key.

    The test has no meaning on two different pair sets, thus a set that
    does not agree raises.
    """
    baseline_ranks = {str(row["pair_key"]): int(row["target_rank"])  # type: ignore[call-overload]
                      for row in baseline}
    candidate_ranks = {str(row["pair_key"]): int(row["target_rank"])  # type: ignore[call-overload]
                       for row in candidate}
    if not baseline_ranks or set(baseline_ranks) != set(candidate_ranks):
        raise ValueError(
            "the two V1 runs do not hold the same pairs: "
            f"{len(baseline_ranks)} and {len(candidate_ranks)} keys, "
            f"{len(set(baseline_ranks) & set(candidate_ranks))} shared")
    count = len(baseline_ranks)
    candidate_only = baseline_only = 0
    for key, rank in baseline_ranks.items():
        base_first = rank == 1
        cand_first = candidate_ranks[key] == 1
        candidate_only += int(cand_first and not base_first)
        baseline_only += int(base_first and not cand_first)
    return PairedTable(
        pair_count=count,
        baseline_first=sum(r == 1 for r in baseline_ranks.values()) / count,
        candidate_first=sum(r == 1 for r in candidate_ranks.values()) / count,
        baseline_top_ten=sum(r <= _TOP_TEN for r in baseline_ranks.values()) / count,
        candidate_top_ten=sum(r <= _TOP_TEN for r in candidate_ranks.values()) / count,
        candidate_only=candidate_only,
        baseline_only=baseline_only,
        mcnemar_p=mcnemar_exact_p(candidate_only, baseline_only),
    )


def decoy_parity(baseline: Sequence[Mapping[str, object]],
                 candidate: Sequence[Mapping[str, object]]) -> DecoyParity:
    """Compare the decoy counts of two V1 trial sets by pair_key.

    The two sets hold the same pairs: paired_table checks that first.
    """
    baseline_decoys = {str(row["pair_key"]): int(row["decoy_count"])  # type: ignore[call-overload]
                       for row in baseline}
    fewer = more = lost_first = first = 0
    candidate_decoys: list[int] = []
    for row in candidate:
        decoys = int(row["decoy_count"])  # type: ignore[call-overload]
        candidate_decoys.append(decoys)
        is_first = int(row["target_rank"]) == 1  # type: ignore[call-overload]
        first += int(is_first)
        difference = decoys - baseline_decoys[str(row["pair_key"])]
        fewer += int(difference < 0)
        more += int(difference > 0)
        lost_first += int(is_first and difference < 0)
    return DecoyParity(
        baseline_counts=_histogram(baseline_decoys.values()),
        candidate_counts=_histogram(candidate_decoys),
        candidate_fewer=fewer,
        candidate_more=more,
        conservative_first=(first - lost_first) / len(candidate_decoys),
    )


def _histogram(values) -> tuple[tuple[int, int], ...]:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(sorted(counts.items()))


def rule_lines(table: PairedTable, parity: DecoyParity, mode: str,
               v2_significances: Mapping[str, float]) -> list[RuleLine]:
    """The adoption rule of spec VE1 section 6, line by line.

    mode is the submission mode of the two V1 runs. The first-rank
    floor is a sketch number and shows for a sketch run alone. A mixed
    run has no rule and gives the decoy line alone.

    v2_significances holds the candidate's KS significance by V2 mode.
    Each mode rule 3 names gets a line, and a mode with no record gives
    a line that does not hold: a report with rule 3 not in it reads as
    a clear one.

    The decoy line is not one of the three rules. Section 5 of the spec
    says the numbers wait for the threshold ruling when the grouping
    moves, and this line is where a reader sees that it moved.
    """
    if mode not in V2_MODES_FOR:
        raise ValueError(f"unknown submission mode: {mode!r}")
    lines = [RuleLine(
        "equal decoy counts",
        parity.candidate_fewer == 0 and parity.candidate_more == 0,
        f"candidate holds fewer decoys on {parity.candidate_fewer} pairs "
        f"and more on {parity.candidate_more}")]
    if mode != "mixed":
        higher = table.candidate_first >= table.baseline_first
        lines.append(RuleLine(
            "not below the baseline",
            higher or table.mcnemar_p >= SIGNIFICANCE_LINE,
            f"{table.candidate_first:.3f} against {table.baseline_first:.3f}, "
            f"McNemar p {table.mcnemar_p:.4f}"))
    if mode == "sketch":
        lines.append(RuleLine(
            "first-rank floor",
            table.candidate_first >= FIRST_RANK_FLOOR,
            f"{table.candidate_first:.3f} against {FIRST_RANK_FLOOR}"))
    for v2_mode in V2_MODES_FOR[mode]:
        if v2_mode in v2_significances:
            significance = v2_significances[v2_mode]
            lines.append(RuleLine(
                f"V2 uniform, {v2_mode}", significance > SIGNIFICANCE_LINE,
                f"KS significance {significance:.4f}"))
        else:
            lines.append(RuleLine(
                f"V2 uniform, {v2_mode}", False,
                "no V2 record of this mode was given"))
    return lines


def similarity_quantiles(reports: Sequence[Mapping[str, object]]
                         ) -> dict[str, float] | None:
    """The quantiles of atom similarity in one V1 run's match reports.

    Sinkhorn epsilon and its reserve read this scale (spec VE1 section
    5). A sketch-mode run has no atoms and gives None.
    """
    values = sorted(
        float(atom["similarity"])
        for report in reports
        for atom in report["atoms"]  # type: ignore[attr-defined]
    )
    if not values:
        return None

    def at(fraction: float) -> float:
        return values[min(len(values) - 1, int(fraction * len(values)))]

    return {"p10": at(0.10), "p50": at(0.50), "p90": at(0.90),
            "max": values[-1], "count": float(len(values))}


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def _read_record(record_path: Path, harness_name: str) -> dict:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("harness") != harness_name:
        raise ValueError(
            f"{record_path}: not a {harness_name} record, the harness field "
            f"is {record.get('harness')!r}")
    return record


def _run_directory(record: Mapping[str, object], data_root: Path) -> Path:
    return harness.validation_dir(data_root, str(record["harness"]),
                                  str(record["index_id"]),
                                  str(record["harness_config_hash"]))


def _run_mode(record_path: Path, record: Mapping[str, object],
              data_root: Path) -> str:
    """The submission mode of one run, from the meta file of its data.

    A record holds no mode. A meta file that is not there or that names
    a different run raises: a mode from a different run is a plausible
    value that is incorrect.
    """
    meta_path = _run_directory(record, data_root) / "meta.json"
    if not meta_path.is_file():
        raise ValueError(
            f"{record_path}: no meta file at {meta_path} - the run data "
            "is not on this machine")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("harness_config_hash") != record["harness_config_hash"]:
        raise ValueError(
            f"{meta_path}: the meta file names a different run than "
            f"{record_path}")
    return str(meta["submission_mode"])


def checked_trials(record_path: Path, record: Mapping[str, object],
                   trials: Sequence[Mapping[str, object]]) -> None:
    """Refuse trial rows that do not agree with their V1 record.

    The rows sit in the data cache, and a second V1 run writes them
    again while a record with a verdict stays. The first-rank fraction
    of the rows must equal the value in the record.
    """
    if not trials:
        raise ValueError(f"{record_path}: the run holds no trial row")
    first = sum(int(row["target_rank"]) == 1  # type: ignore[call-overload]
                for row in trials) / len(trials)
    if harness.quantized(first) != record["first_rank_fraction"]:
        raise ValueError(
            f"{record_path}: the record says first rank "
            f"{record['first_rank_fraction']} and the trial rows give "
            f"{harness.quantized(first)} - the rows moved after the record")


def v2_significances(record_paths: Sequence[Path],
                     candidate: Mapping[str, object], candidate_mode: str,
                     data_root: Path) -> dict[str, float]:
    """The KS significance of the candidate's V2 records, by mode.

    A V2 record is evidence for the candidate when it has the
    candidate's preparation. The record of the candidate's own mode
    comes from the same scoring config as the V1 run, thus it also has
    the candidate's scoring config hash. A record that does not agree
    raises, and a second record of one mode raises.
    """
    values: dict[str, float] = {}
    for path in record_paths:
        record = _read_record(path, "v2")
        if (record["preparation_version_id"]
                != candidate["preparation_version_id"]):
            raise ValueError(
                f"{path}: this V2 record is not the candidate's - its "
                "preparation is "
                f"{str(record['preparation_version_id'])[:8]} and the "
                "candidate's is "
                f"{str(candidate['preparation_version_id'])[:8]}")
        mode = _run_mode(path, record, data_root)
        if mode in values:
            raise ValueError(f"{path}: a second V2 record of mode {mode!r}")
        if (mode == candidate_mode and record["scoring_config_hash"]
                != candidate["scoring_config_hash"]):
            raise ValueError(
                f"{path}: this V2 record is not the candidate's - it has "
                "the candidate's mode and a different scoring config hash")
        values[mode] = float(record["ks_significance"])
    return values


def format_report(table: PairedTable, parity: DecoyParity, mode: str,
                  lines: Sequence[RuleLine],
                  baseline_similarity: Mapping[str, float] | None,
                  candidate_similarity: Mapping[str, float] | None) -> str:
    def counts(histogram: tuple[tuple[int, int], ...]) -> str:
        return "  ".join(f"{decoys} x{pairs}" for decoys, pairs in histogram)

    rows = [
        f"submission mode       {mode}",
        f"pairs                 {table.pair_count}",
        f"first rank            baseline {table.baseline_first:.3f}   "
        f"candidate {table.candidate_first:.3f}",
        f"top ten               baseline {table.baseline_top_ten:.3f}   "
        f"candidate {table.candidate_top_ten:.3f}",
        f"discordant pairs      candidate only {table.candidate_only}   "
        f"baseline only {table.baseline_only}",
        f"McNemar exact p       {table.mcnemar_p:.4f}",
        f"decoy counts          baseline {counts(parity.baseline_counts)}",
        f"decoy counts          candidate {counts(parity.candidate_counts)}",
        f"first rank, candidate, fewer-decoy pairs counted as not first"
        f"   {parity.conservative_first:.3f}",
    ]
    for name, quantiles in (("baseline", baseline_similarity),
                            ("candidate", candidate_similarity)):
        if quantiles is not None:
            rows.append(f"atom similarity       {name} " + "  ".join(
                f"{key} {value:.3f}" for key, value in quantiles.items()))
    rows.append("")
    rows.extend(f"{'holds ' if line.holds else 'FAILS '} {line.name}: {line.detail}"
                for line in lines)
    if mode == "mixed":
        rows.append("No adoption rule reads a mixed V1 run "
                    "(spec VE1 section 6).")
    if not lines[0].holds:
        rows.append("The decoy counts moved: the numbers wait for the "
                    "threshold ruling (spec VE1 section 5).")
    rows.append("")
    rows.append("The verdict is the owner's (spec VE1 section 9).")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.bakeoff")
    parser.add_argument("--baseline", required=True, type=Path,
                        help="the V1 record of the baseline encoder")
    parser.add_argument("--candidate", required=True, type=Path,
                        help="the V1 record of the candidate encoder")
    parser.add_argument("--v2", action="append", default=[], type=Path,
                        help="a V2 record of the candidate, one for each mode")
    parser.add_argument("--data-root", default="data", type=Path)
    arguments = parser.parse_args(argv)
    data_root = arguments.data_root
    baseline = _read_record(arguments.baseline, "v1")
    candidate = _read_record(arguments.candidate, "v1")
    mode = _run_mode(arguments.baseline, baseline, data_root)
    candidate_mode = _run_mode(arguments.candidate, candidate, data_root)
    if mode != candidate_mode:
        raise ValueError(
            f"the two V1 runs have different submission modes: {mode!r} "
            f"and {candidate_mode!r}")
    baseline_dir = _run_directory(baseline, data_root)
    candidate_dir = _run_directory(candidate, data_root)
    baseline_trials = _read_jsonl(baseline_dir / "trials.jsonl")
    candidate_trials = _read_jsonl(candidate_dir / "trials.jsonl")
    checked_trials(arguments.baseline, baseline, baseline_trials)
    checked_trials(arguments.candidate, candidate, candidate_trials)
    table = paired_table(baseline_trials, candidate_trials)
    parity = decoy_parity(baseline_trials, candidate_trials)
    v2_values = v2_significances(arguments.v2, candidate, mode,
                                 data_root)
    print(format_report(
        table, parity, mode, rule_lines(table, parity, mode, v2_values),
        similarity_quantiles(_read_jsonl(baseline_dir / "match_reports.jsonl")),
        similarity_quantiles(_read_jsonl(candidate_dir / "match_reports.jsonl")),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
