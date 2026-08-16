"""The player rollups and the two boards (spec M1 section 7).

The reveal folds each stored trial row into one pair for each
player, writes the day's board, and rebuilds the skill board. The
player endpoints then read a prepared file and calculate nothing.

This module walks the store, thus it sits adjacent to the server
and not in pipeline/: pipeline must not import from here, and there is
no path back. It writes into the data root alone. The store is a
permanent record and nothing here adds to it, which the snapshot
tests hold.

No clock. Each timestamp comes from the day record the reveal
wrote first, thus a second run writes equal bytes and the
additive path and a full assembly agree.
"""

import argparse
import math
import sys
from pathlib import Path

from core import aggregate
from core.canonical import JsonValue, sha256_hex
from pool.artifacts import write_json_pretty
from service import store
from service.config import (ServiceConfig, ServiceConfigError,
                            load_service_config)
from validation.harness import quantized

_PAIR_FIELDS = ("player", "scoring_config_hash", "preparation_version_id",
                "n", "clamp_count", "s_statistic", "days", "degenerate",
                "updated_at")

# The band the funnel chart draws, at a ladder of trial counts.
# The server owns it: the limit is a Layer 9 shape in the
# no-change tier, and a second copy of it in a browser is what
# the wire types forbid.
_BAND_STEPS = 12


class RollupError(ValueError):
    """A rollup rule was broken or a stored artifact did not parse."""


def skill_pair_path(data_root: Path, player: str,
                    scoring_hash: str) -> Path:
    return data_root / "skill" / f"{player}.{scoring_hash[:8]}.json"


def leaderboard_path(data_root: Path, day: str, scoring_hash: str) -> Path:
    return data_root / "leaderboards" / f"{day}.{scoring_hash[:8]}.json"


def skill_board_path(data_root: Path, scoring_hash: str) -> Path:
    return data_root / f"skill-board.{scoring_hash[:8]}.json"


def board_seed(scoring_hash: str, day: str) -> int:
    """The rank simulation's seed, from recorded inputs alone.

    A function of the configuration and the day, thus the additive
    path and a full assembly agree and a reader can reproduce the
    board. It digests no floating-point text.
    """
    return int(sha256_hex(f"skill-board:{scoring_hash}:{day}")[:16], 16)


def read_pair(path: Path, *, scoring_hash: str,
              preparation_version_id: str) -> dict | None:
    """One stored pair, checked against the full hash, or None.

    The file name holds eight characters of the hash and the
    document holds the full one. This compares them, thus two
    configurations that share a prefix cannot silently share a
    cache entry.
    """
    value = store.read_json_or_none(path)
    if value is None:
        return None
    if set(value) != set(_PAIR_FIELDS):
        raise RollupError(
            f"{path}: the pair must have the fields {sorted(_PAIR_FIELDS)}")
    if value["scoring_config_hash"] != scoring_hash:
        raise RollupError(
            f"{path}: the stored scoring hash is not the one asked for - "
            f"a truncated-key collision")
    if value["preparation_version_id"] != preparation_version_id:
        raise RollupError(
            f"{path}: the stored preparation version is not the one asked "
            f"for - a truncated-key collision")
    return value


def fold_day(pair: dict | None, *, player: str, day: str, term: float,
             clamped: bool, scoring_hash: str,
             preparation_version_id: str, updated_at: str) -> dict:
    """Add one day's term to a player's pair. Pure.

    The days sequence is what makes the fold repeatable. A day that
    is listed is skipped, thus a second reveal, a stop and a retry,
    and a full assembly each land on the same bytes. A scalar of
    the newest day in its position can double-count a backfill and
    say nothing.

    The S statistic keeps its full precision. The next fold reads
    that sum again, and a rounded sum can collect 5e-7 at each
    day. The boards quantize, because a board reports.
    """
    if pair is not None and day in pair["days"]:
        return pair
    if pair is None:
        pair = {"player": player, "scoring_config_hash": scoring_hash,
                "preparation_version_id": preparation_version_id,
                "n": 0, "clamp_count": 0, "s_statistic": 0.0,
                "days": [], "degenerate": True, "updated_at": updated_at}
    total = pair["s_statistic"] + term
    return {**pair,
            "n": pair["n"] + 1,
            "clamp_count": pair["clamp_count"] + (1 if clamped else 0),
            "s_statistic": total,
            "days": sorted([*pair["days"], day]),
            "degenerate": total <= 0.0,
            "updated_at": max(pair["updated_at"], updated_at)}


def term_of(p: float) -> tuple[float, bool]:
    """The negative logarithm of one trial score, and its clamp.

    One clamp rule for the full system: skill_summary holds it,
    thus this reads that function and no second rule can drift away
    from it.
    """
    summary = aggregate.skill_summary([p], unbiased=False)
    return summary.s_statistic, summary.clamp_count == 1


def daily_board_value(record: store.DayRecord,
                      rows: list[tuple[str, dict]]) -> dict[str, JsonValue]:
    """The day's board. Pure.

    Sorted by the trial score down. Players with an equal score
    share the smaller rank, and the sequence breaks an equal score
    by the player name, thus two runs give equal bytes.

    The store key travels and the board label does not: the
    endpoint joins to the player record at read time, which is one
    file read, and an edited label then wants no new assembly.

    A player with 1.0 at each trial score ranks here in the usual
    manner (the 2026-08-16 ruling). This board reads the trial
    score and takes no logarithm, thus that player holds a position
    while they have no skill number.

    Two ranks travel and they count different things. rank is the
    position on this board, in the set of players. target_rank is
    the position of the target in the set of images, which is the
    number the reveal card prints with the decoy count. A board
    that carries one alone makes the reader answer with the other.
    """
    ordered = sorted(rows, key=lambda item: (-item[1]["p"], item[0]))
    board: list[dict[str, JsonValue]] = []
    for position, (player, row) in enumerate(ordered):
        rank = position + 1
        if position and row["p"] == ordered[position - 1][1]["p"]:
            rank = board[-1]["rank"]
        board.append({"player": player, "p": row["p"],
                      "target_rank": row["target_rank"],
                      "decoy_count": row["decoy_count"], "rank": rank})
    return {"day": record.day,
            "scoring_config_hash": record.scoring_config_hash,
            "preparation_version_id": record.preparation_version_id,
            "row_count": len(board),
            "created_at": record.revealed_at,
            "rows": board}


def board_is_current(board: dict) -> bool:
    """Does a stored day board hold each field the wire wants?

    A board written before the target rank travelled holds the
    board position alone. Its rows cannot answer the position of
    the target in the set of images, thus a reader that finds one
    assembles the rows again from the trial rows, which are
    permanent. The other path is to answer the board position with
    the name of the target rank, which is the fault this stops.
    """
    return all("target_rank" in row for row in board["rows"])


def _band(counts: list[int], mu: float) -> list[dict[str, JsonValue]]:
    """The no-skill range at a ladder of trial counts.

    The limits are mu plus and minus 1.96 times the square root of
    trigamma(n). The ladder is spaced on the logarithmic scale,
    because a straight one piles each low-trial player at one end.
    """
    low, high = min(counts), max(counts)
    if low == high:
        ladder = [low]
    else:
        span = math.log(high) - math.log(low)
        ladder = sorted({
            max(1, round(math.exp(math.log(low)
                                  + span * step / (_BAND_STEPS - 1))))
            for step in range(_BAND_STEPS)})
    rows = []
    for n in ladder:
        spread = 1.96 * math.sqrt(aggregate.trigamma(n))
        rows.append({"n": n, "low": quantized(mu - spread),
                     "high": quantized(mu + spread)})
    return rows


def _row_order(row: dict) -> tuple:
    """Eligible players by expected rank, then the others by trials.

    One total sequence, thus two assemblies give equal bytes. The
    ineligible run reads by trial count down, which puts the player
    who is nearest the floor at its head.
    """
    if row["eligible"]:
        return (0, row["expected_rank"], row["player"])
    return (1, -row["n"], row["player"])


def skill_board_value(pairs: list[dict], *, scoring_hash: str,
                      preparation_version_id: str, day: str, seed: int,
                      created_at: str | None) -> dict[str, JsonValue]:
    """The skill board. Pure, and each reported number quantized.

    Membership is the architecture's own floor of 30 trials and
    stays there (the 2026-08-16 ruling). The recomputed floor rides
    along as a report: it becomes larger as the population gets
    tight, and at a width of 0.05 it asks for 401 trials, which in
    a daily game is more than a year. A fairness floor that empties
    its own board is not serving fairness, and the rank interval
    holds the honesty for a player with a small trial count.

    active is calculated and is not a switch: one eligible player
    turns the board on, and provisional stands until the population
    floor. A new deployment thus gates itself with no operator
    step.

    Each player holds a row and the eligible players hold a rank
    (ruling 17 of 2026-08-16). A player below the trial floor keeps
    their skill number and their evidence value, because the two
    read their own pair alone, and their shrunk value, expected
    rank, and rank interval are None. The fit and the rank
    simulation read the eligible set, thus to give an ineligible
    player a rank moves the rank of each other player. The chart
    plots each row and the ranked table reads the eligible ones:
    that is what lets a player read the low-trial scatter as noise
    (section 9) while membership stays at the floor.

    A player with 1.0 at each trial score has no skill number, thus
    they stay off this board and degenerate_count says how many.
    They keep their position on each day's board.
    """
    usable = [pair for pair in pairs if not pair["degenerate"]]
    points = {pair["player"]: aggregate.population_point(
        pair["n"], pair["s_statistic"]) for pair in usable}
    eligible = [pair for pair in usable
                if pair["n"] >= aggregate.ELIGIBLE_TRIAL_FLOOR]
    eligible_points = [points[pair["player"]] for pair in eligible]
    fit = aggregate.fit_population(eligible_points)
    body: dict[str, JsonValue] = {
        "scoring_config_hash": scoring_hash,
        "preparation_version_id": preparation_version_id,
        "day": day,
        "created_at": created_at,
        "active": len(eligible) >= 1,
        "player_count": len(usable),
        "eligible_count": len(eligible),
        "degenerate_count": len(pairs) - len(usable),
        "eligibility_floor": aggregate.ELIGIBLE_TRIAL_FLOOR,
        "recomputed_floor": None,
        "fit_floor": aggregate.FIT_PLAYER_FLOOR,
        "provisional": len(eligible) < aggregate.FIT_PLAYER_FLOOR,
        "rank_seed": seed,
        "rank_sample_count": aggregate.RANK_SAMPLE_COUNT,
        "rows": [],
        "population": None,
        "variation": None,
        "baseline": None,
        "stopping_monitor": None,
        "discovery": None,
        "baseline_band": [],
    }
    if not eligible:
        return body
    if (fit.fitted and fit.tau > 0.0
            and len(eligible) >= aggregate.PUBLISHABLE_PLAYER_COUNT):
        body["recomputed_floor"] = aggregate.recomputed_trial_floor(fit.tau)
    body["population"] = {
        "mu": quantized(fit.mu), "tau": quantized(fit.tau),
        "mu_spread": quantized(fit.mu_spread), "fitted": fit.fitted,
        "halvings": fit.halvings}
    body["baseline_band"] = _band([pair["n"] for pair in eligible], fit.mu)
    if len(eligible) >= 2:
        report = aggregate.variation_report(eligible_points, fit)
        body["variation"] = {
            "q_statistic": quantized(report.q_statistic),
            "dof": report.dof,
            "q_significance": quantized(report.q_significance),
            "tau_low": quantized(report.tau_low),
            "tau_high": (None if report.tau_high is None
                         else quantized(report.tau_high)),
            "tau_multiplicative": quantized(report.tau_multiplicative),
            "prediction_low": quantized(report.prediction_low),
            "prediction_high": quantized(report.prediction_high)}
        check = aggregate.baseline_check(eligible_points)
        body["baseline"] = {
            "statistic": quantized(check.statistic),
            "significance": quantized(check.significance),
            "player_count": check.player_count}
        monitor = aggregate.stopping_monitor(eligible_points, fit)
        body["stopping_monitor"] = {
            "player_count": monitor.player_count,
            "correlation": (None if monitor.correlation is None
                            else quantized(monitor.correlation))}
    posteriors = [aggregate.posterior_normal(points[pair["player"]], fit)
                  for pair in eligible]
    ranks = aggregate.posterior_ranks(posteriors, seed=seed)
    ranked = {pair["player"]: (posterior, rank) for pair, posterior, rank
              in zip(eligible, posteriors, ranks)}
    fixed_values, rows = [], []
    for pair in usable:
        point = points[pair["player"]]
        summary = aggregate.summary_of_pair(
            pair["n"], pair["s_statistic"],
            clamp_count=pair["clamp_count"], unbiased=pair["n"] >= 2)
        evidence = aggregate.anytime_evidence(pair["n"],
                                              pair["s_statistic"])
        posterior, rank = ranked.get(pair["player"], (None, None))
        if rank is not None:
            fixed_values.append(summary.evidence_p)
        rows.append({
            "player": pair["player"], "n": pair["n"],
            "eligible": rank is not None,
            "theta": quantized(summary.theta),
            "shrunk": (None if posterior is None
                       else quantized(posterior.mean)),
            "y": quantized(point.y), "v": quantized(point.v),
            "expected_rank": (None if rank is None
                              else quantized(rank.expected_rank)),
            "rank_low": None if rank is None else rank.rank_low,
            "rank_high": None if rank is None else rank.rank_high,
            "evidence_p": quantized(summary.evidence_p),
            "log_e_value": quantized(evidence.log_e_value),
            "anytime_significance": quantized(evidence.significance)})
    rows.sort(key=_row_order)
    body["rows"] = rows
    claim = aggregate.discovery_report(fixed_values)
    body["discovery"] = {
        "level": claim.level, "tested": claim.tested,
        "flagged": claim.flagged,
        "expected_by_luck": quantized(claim.expected_by_luck)}
    return body


# ---- the imperative shell ----


def _row_for(root: Path, day: str, player: str,
             scoring_hash: str, canonical: str) -> dict | None:
    """The player's trial row for one day at one configuration.

    The day's own row when the day ran at that configuration, the
    adjacent rescore row when one is stored, and None when the two
    are missing. That is what lets an assembly at a new hash build
    a full parallel board while the first board's bytes do not
    move.
    """
    if scoring_hash == canonical:
        return store.read_json_or_none(
            store.trial_row_path(root, day, player))
    return store.read_json_or_none(
        store.trial_row_path(root, day, player, scoring_hash[:8]))


def _fold_into(pairs: dict[str, dict], record: store.DayRecord,
               root: Path, scoring_hash: str) -> int:
    """Fold one revealed day into the pairs. Answers the row count."""
    count = 0
    for player in store.list_submissions(root, record.day):
        row = _row_for(root, record.day, player, scoring_hash,
                       record.scoring_config_hash)
        if row is None:
            continue
        term, clamped = term_of(float(row["p"]))
        pairs[player] = fold_day(
            pairs.get(player), player=player, day=record.day, term=term,
            clamped=clamped, scoring_hash=scoring_hash,
            preparation_version_id=record.preparation_version_id,
            updated_at=record.revealed_at or record.opened_at)
        count += 1
    return count


def _write_boards(service_config: ServiceConfig, record: store.DayRecord,
                  pairs: dict[str, dict], scoring_hash: str) -> None:
    """Write each pair, the day's board, and the skill board."""
    data_root = Path(service_config.data_root)
    root = Path(service_config.store_root)
    for player, pair in sorted(pairs.items()):
        write_json_pretty(skill_pair_path(data_root, player, scoring_hash),
                          pair)
    rows = []
    for player in store.list_submissions(root, record.day):
        row = _row_for(root, record.day, player, scoring_hash,
                       record.scoring_config_hash)
        if row is not None:
            rows.append((player, row))
    write_json_pretty(leaderboard_path(data_root, record.day, scoring_hash),
                      daily_board_value(record, rows))
    write_json_pretty(
        skill_board_path(data_root, scoring_hash),
        skill_board_value(
            sorted(pairs.values(), key=lambda pair: pair["player"]),
            scoring_hash=scoring_hash,
            preparation_version_id=record.preparation_version_id,
            day=record.day, seed=board_seed(scoring_hash, record.day),
            created_at=record.revealed_at))


def roll_up_day(service_config: ServiceConfig,
                record: store.DayRecord) -> dict[str, int]:
    """Fold one revealed day and assemble the boards again.

    The reveal uses this after the status move (the 2026-08-16
    ruling). Each write is repeatable, thus a stop part of the
    procedure is repaired by a second reveal or by the assemble
    command, and the boards do not go stale while the process
    runs.
    """
    if record.status != "revealed":
        raise RollupError(
            f"day {record.day} has status {record.status!r} and the rollup "
            f"wants 'revealed'")
    data_root = Path(service_config.data_root)
    scoring_hash = record.scoring_config_hash
    pairs: dict[str, dict] = {}
    for player in _players_with_pairs(data_root, scoring_hash):
        stored = read_pair(
            skill_pair_path(data_root, player, scoring_hash),
            scoring_hash=scoring_hash,
            preparation_version_id=record.preparation_version_id)
        if stored is not None:
            pairs[player] = stored
    folded = _fold_into(pairs, record, Path(service_config.store_root),
                        scoring_hash)
    _write_boards(service_config, record, pairs, scoring_hash)
    return {"days": 1, "players": len(pairs), "rows": folded}


def _players_with_pairs(data_root: Path, scoring_hash: str) -> list[str]:
    """The player names with a stored pair at this configuration."""
    root = data_root / "skill"
    if not root.is_dir():
        return []
    suffix = f".{scoring_hash[:8]}.json"
    return sorted(entry.name[:-len(suffix)] for entry in root.iterdir()
                  if entry.is_file() and entry.name.endswith(suffix))


def assemble(service_config: ServiceConfig, *,
             scoring_hash: str | None = None) -> dict[str, int]:
    """Assemble each pair and each board from the store again.

    The repair path. It builds from nothing and overwrites, and it
    does not fold into what is there: a pair that was counted two
    times must be fixable.

    With no hash it uses the newest revealed day's configuration.
    With one, it reads the adjacent rescore rows, thus an assembly
    after a rescore builds a full parallel board and the first
    board's bytes do not move.
    """
    root = Path(service_config.store_root)
    revealed = [day for day in store.list_days(root)
                if store.read_day_record(root, day).status == "revealed"]
    if not revealed:
        return {"days": 0, "players": 0, "rows": 0}
    newest = store.read_day_record(root, revealed[-1])
    chosen = scoring_hash or newest.scoring_config_hash
    pairs: dict[str, dict] = {}
    counts = {"days": 0, "players": 0, "rows": 0}
    last = None
    for day in revealed:
        record = store.read_day_record(root, day)
        rows = _fold_into(pairs, record, root, chosen)
        if rows:
            counts["days"] += 1
            counts["rows"] += rows
            last = record
    if last is None:
        return counts
    for day in revealed:
        record = store.read_day_record(root, day)
        data_root = Path(service_config.data_root)
        day_rows = []
        for player in store.list_submissions(root, day):
            row = _row_for(root, day, player, chosen,
                           record.scoring_config_hash)
            if row is not None:
                day_rows.append((player, row))
        if day_rows:
            write_json_pretty(leaderboard_path(data_root, day, chosen),
                              daily_board_value(record, day_rows))
    _write_boards(service_config, last, pairs, chosen)
    counts["players"] = len(pairs)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.rollup")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    commands = parser.add_subparsers(dest="command", required=True)
    assemble_parser = commands.add_parser("assemble")
    assemble_parser.add_argument("--scoring-config-hash", default=None)
    arguments = parser.parse_args(argv)

    try:
        service_config = load_service_config(Path(arguments.service_config))
        if arguments.command == "assemble":
            counts = assemble(service_config,
                              scoring_hash=arguments.scoring_config_hash)
            print("assemble "
                  + "  ".join(f"{name}={value}"
                              for name, value in sorted(counts.items())))
    except (ServiceConfigError, store.StoreError, RollupError,
            ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
