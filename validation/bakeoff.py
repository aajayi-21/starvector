"""The paired table of one encoder against a different encoder (spec VE1).

Spec: docs/specs/voyage-encoder.md section 6. It reads the pair rows
of two V1 runs on the same sketch pairs, and the KS values of their V2
runs. It reports the rule lines and changes no config. The verdict is
the owner's. No live player trial enters this tool (I6): V1 pairs have
a known correspondence by construction.
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


def rule_lines(table: PairedTable,
               v2_significances: Mapping[str, float]) -> list[RuleLine]:
    """The adoption rule of spec VE1 section 6, line by line."""
    higher = table.candidate_first >= table.baseline_first
    lines = [
        RuleLine(
            "not below the baseline",
            higher or table.mcnemar_p >= SIGNIFICANCE_LINE,
            f"{table.candidate_first:.3f} against {table.baseline_first:.3f}, "
            f"McNemar p {table.mcnemar_p:.4f}"),
        RuleLine(
            "first-rank floor",
            table.candidate_first >= FIRST_RANK_FLOOR,
            f"{table.candidate_first:.3f} against {FIRST_RANK_FLOOR}"),
    ]
    lines.extend(
        RuleLine(f"V2 uniform, {name}", significance > SIGNIFICANCE_LINE,
                 f"KS significance {significance:.4f}")
        for name, significance in sorted(v2_significances.items()))
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


def _run_directory(record_path: Path, data_root: Path) -> Path:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    return harness.validation_dir(data_root, "v1", record["index_id"],
                                  record["harness_config_hash"])


def _ks_significance(record_path: Path) -> float:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    return float(record["ks_significance"])


def format_report(table: PairedTable, lines: Sequence[RuleLine],
                  baseline_similarity: Mapping[str, float] | None,
                  candidate_similarity: Mapping[str, float] | None) -> str:
    rows = [
        f"pairs                 {table.pair_count}",
        f"first rank            baseline {table.baseline_first:.3f}   "
        f"candidate {table.candidate_first:.3f}",
        f"top ten               baseline {table.baseline_top_ten:.3f}   "
        f"candidate {table.candidate_top_ten:.3f}",
        f"discordant pairs      candidate only {table.candidate_only}   "
        f"baseline only {table.baseline_only}",
        f"McNemar exact p       {table.mcnemar_p:.4f}",
    ]
    for name, quantiles in (("baseline", baseline_similarity),
                            ("candidate", candidate_similarity)):
        if quantiles is not None:
            rows.append(f"atom similarity       {name} " + "  ".join(
                f"{key} {value:.3f}" for key, value in quantiles.items()))
    rows.append("")
    rows.extend(f"{'holds ' if line.holds else 'FAILS '} {line.name}: {line.detail}"
                for line in lines)
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
    baseline_dir = _run_directory(arguments.baseline, arguments.data_root)
    candidate_dir = _run_directory(arguments.candidate, arguments.data_root)
    table = paired_table(_read_jsonl(baseline_dir / "trials.jsonl"),
                         _read_jsonl(candidate_dir / "trials.jsonl"))
    v2_values = {path.stem: _ks_significance(path) for path in arguments.v2}
    print(format_report(
        table, rule_lines(table, v2_values),
        similarity_quantiles(_read_jsonl(baseline_dir / "match_reports.jsonl")),
        similarity_quantiles(_read_jsonl(candidate_dir / "match_reports.jsonl")),
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
