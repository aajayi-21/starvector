"""The day lifecycle commands: open, close, reveal, status, rescore.

Spec: S1 (in docs/specs/) section 6. Each status move is deliberate,
repeatable, and refuses to run out of sequence. Open publishes the
commitment and spends nothing (R5). Close is the one live step.
Reveal publishes the secret. No command prints score information
while the day is open (R3 covers the terminal).
"""

import argparse
import datetime
import secrets
import string
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from core.canonical import canonical_json_pretty, sha256_hex
from pipeline.config import ConfigError, load_scoring_config
from service import scoring, store
from service.config import (ServiceConfig, ServiceConfigError,
                            load_service_config)
from validation import harness


def pick_target(image_ids: tuple[str, ...], day: str,
                pick_seed: str) -> str:
    """The day's target: a seeded, equally likely pick (R6).

    The validation.v2 target rule with the day and the seed in the
    digest. The modulo bias is below N / 2**64 and is accepted, as
    there.
    """
    value = int(sha256_hex(f"day-target:{day}:{pick_seed}")[:16], 16)
    return image_ids[value % len(image_ids)]


def day_commitment(target_id: str, secret: str) -> str:
    """The published digest: SHA-256 of "target:secret" (D-OP8)."""
    return sha256_hex(f"{target_id}:{secret}")


def make_trial_code() -> str:
    """Six random characters, A-Z and 0-9 - the player-facing
    identifier of the hidden target (section 14b ruling). No
    derivation from the image (section 22)."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _local_day() -> str:
    """The owner machine's local date, ISO shape (D8)."""
    return datetime.date.today().isoformat()


def _resolve_day(service_config: ServiceConfig, date: str | None) -> str:
    """The named day, or the latest stored one."""
    if date is not None:
        return date
    day = store.latest_day(Path(service_config.store_root))
    if day is None:
        raise store.StoreError(
            "the store holds no day - open one first")
    return day


def open_day(service_config: ServiceConfig, *, date: str | None = None,
             scoring_config_path: str | None = None,
             clock: Callable[[], str] | None = None,
             pick_seed: str | None = None,
             secret: str | None = None,
             trial_code: str | None = None) -> store.DayRecord:
    """Open one day: wire warm, pick, commit, write (spec section 6)."""
    clock = clock or harness.default_clock
    day = date or _local_day()
    root = Path(service_config.store_root)
    if store.day_record_path(root, day).is_file():
        raise store.StoreError(f"day {day} exists - open refuses a rewrite")
    config_path = scoring_config_path or service_config.scoring_config
    config = load_scoring_config(Path(config_path))
    wired = scoring.wire_for_open(config, config_path,
                                  Path(service_config.data_root))
    pick_seed = pick_seed or secrets.token_hex(16)
    secret = secret or secrets.token_hex(32)
    trial_code = trial_code or make_trial_code()
    target_id = pick_target(wired.context.index.image_ids, day, pick_seed)
    record = store.DayRecord(
        day=day, trial_code=trial_code, target_id=target_id,
        pick_seed=pick_seed, secret=secret,
        commitment=day_commitment(target_id, secret),
        scoring_config_path=config_path,
        scoring_config_hash=wired.scoring_hash,
        preparation_version_id=wired.preparation_version_id,
        status="open", opened_at=clock(), closed_at=None, revealed_at=None)
    store.ensure_store(root)
    store.write_day_record(root, record)
    return record


def close_day(service_config: ServiceConfig, *, date: str | None = None,
              providers: Mapping[str, object] | None = None,
              clock: Callable[[], str] | None = None) -> int:
    """Close one day: score each stored submission, flip the status.

    Repeatable after a stop: a stored trial row that equals the
    recomputation is kept, a different one raises, and the status
    flip is the completeness marker. The output is the count of
    trial rows.
    """
    clock = clock or harness.default_clock
    root = Path(service_config.store_root)
    day = _resolve_day(service_config, date)
    record = store.read_day_record(root, day)
    if record.status != "open":
        raise store.StoreError(
            f"day {day} has status {record.status!r} - close needs 'open'")
    config = load_scoring_config(Path(record.scoring_config_path))
    wired = scoring.wire_for_close(config, record.scoring_config_path,
                                   Path(service_config.data_root), providers)
    if wired.scoring_hash != record.scoring_config_hash:
        raise store.StoreError(
            f"the scoring config hash moved since open "
            f"({wired.scoring_hash[:8]} against "
            f"{record.scoring_config_hash[:8]}) - the config file changed "
            "after the day opened")
    count = 0
    for player in store.list_submissions(root, day):
        stored = store.read_json_or_none(
            store.submission_path(root, day, player))
        if stored is None or "record" not in stored \
                or "trial_id" not in stored:
            raise store.StoreError(
                f"day {day}: the submission of {player} does not parse")
        trial, report = scoring.score_stored_submission(
            stored["record"], record.target_id, wired)
        value = scoring.trial_row_value(day, player, str(stored["trial_id"]),
                                        trial, report, wired)
        row_path = store.trial_row_path(root, day, player)
        rendered = canonical_json_pretty(value) + "\n"
        if row_path.is_file():
            if row_path.read_text(encoding="utf-8") != rendered:
                raise store.StoreError(
                    f"{row_path}: a stored trial row differs from the "
                    "recomputation - the lineage moved between close runs")
        else:
            store.write_once_json(row_path, value)
        count += 1
    store.update_day_status(root, day, expect_status="open",
                            new_status="closed",
                            timestamp_field="closed_at", timestamp=clock())
    return count


def reveal_day(service_config: ServiceConfig, *,
               date: str | None = None,
               clock: Callable[[], str] | None = None) -> store.DayRecord:
    """Reveal one closed day: the status move that opens the report."""
    clock = clock or harness.default_clock
    root = Path(service_config.store_root)
    day = _resolve_day(service_config, date)
    return store.update_day_status(root, day, expect_status="closed",
                                   new_status="revealed",
                                   timestamp_field="revealed_at",
                                   timestamp=clock())


def _first_difference(stored: dict, recomputed: dict) -> str:
    """The first field where two trial rows disagree, for the error."""
    for key in sorted(set(stored) | set(recomputed)):
        if stored.get(key) != recomputed.get(key):
            return key
    return "the byte shape"


def rescore_days(service_config: ServiceConfig, *, config_path: str,
                 from_date: str | None = None, to_date: str | None = None,
                 providers: Mapping[str, object] | None = None,
                 ) -> dict[str, int]:
    """Re-run stored submissions with a named config (S1 R8).

    With the pinned config the recomputation must equal the stored
    rows byte-for-byte - a difference names the day, the player, and
    the first differing field, and nothing is written. With a
    different config the rows land adjacent
    (trials/<player>.<hash8>.json), repeatable, and the stored rows
    and day records stay untouched (architecture section 21:
    rescore, do not migrate). Open days are skipped with a count -
    they hold no row at this time.
    """
    import json

    root = Path(service_config.store_root)
    named = load_scoring_config(Path(config_path))
    wired = scoring.wire_for_close(named, config_path,
                                   Path(service_config.data_root),
                                   providers)
    counts = {"days": 0, "compared": 0, "equal": 0, "written": 0,
              "skipped_open": 0}
    for day in store.list_days(root):
        if from_date is not None and day < from_date:
            continue
        if to_date is not None and day > to_date:
            continue
        record = store.read_day_record(root, day)
        if record.status == "open":
            counts["skipped_open"] += 1
            continue
        if record.preparation_version_id != wired.preparation_version_id:
            raise store.StoreError(
                f"day {day} was scored against preparation "
                f"{record.preparation_version_id[:8]} and the named config "
                f"wires {wired.preparation_version_id[:8]} - a rescore "
                "across preparations needs its own ruling")
        counts["days"] += 1
        pinned = wired.scoring_hash == record.scoring_config_hash
        for player in store.list_submissions(root, day):
            stored = store.read_json_or_none(
                store.submission_path(root, day, player))
            if stored is None:
                raise store.StoreError(
                    f"day {day}: the submission of {player} does not parse")
            trial, report = scoring.score_stored_submission(
                stored["record"], record.target_id, wired)
            value = scoring.trial_row_value(
                day, player, str(stored["trial_id"]), trial, report, wired)
            rendered = canonical_json_pretty(value) + "\n"
            if pinned:
                row_path = store.trial_row_path(root, day, player)
                if not row_path.is_file():
                    raise store.StoreError(
                        f"{row_path}: a closed day has no stored trial row")
                counts["compared"] += 1
                current = row_path.read_text(encoding="utf-8")
                if current != rendered:
                    field = _first_difference(json.loads(current), value)
                    raise store.StoreError(
                        f"rescore mismatch on day {day}, player {player}: "
                        f"the first differing field is {field} - the "
                        "pinned config no longer reproduces the stored "
                        "trial row (CLAUDE.md section 9)")
                counts["equal"] += 1
            else:
                adjacent = store.trial_row_path(
                    root, day, player, wired.scoring_hash[:8])
                if adjacent.is_file():
                    if adjacent.read_text(encoding="utf-8") != rendered:
                        raise store.StoreError(
                            f"{adjacent}: an earlier rescore wrote a "
                            "different row for the same config hash")
                    continue
                store.write_once_json(adjacent, value)
                counts["written"] += 1
    return counts


def day_status_lines(service_config: ServiceConfig) -> list[str]:
    """The status text: day, status, and if a submission is stored."""
    root = Path(service_config.store_root)
    day = store.latest_day(root)
    if day is None:
        return ["no day open"]
    record = store.read_day_record(root, day)
    submitted = service_config.player in store.list_submissions(root, day)
    return [
        f"day {day}",
        f"trial code {record.trial_code}",
        f"status {record.status}",
        f"commitment {record.commitment}",
        f"submission stored: {'yes' if submitted else 'no'}",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.day")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    commands = parser.add_subparsers(dest="command", required=True)
    open_parser = commands.add_parser("open")
    open_parser.add_argument("--config", default=None,
                             help="scoring config override")
    open_parser.add_argument("--date", default=None)
    close_parser = commands.add_parser("close")
    close_parser.add_argument("--date", default=None)
    reveal_parser = commands.add_parser("reveal")
    reveal_parser.add_argument("--date", default=None)
    commands.add_parser("status")
    rescore_parser = commands.add_parser("rescore")
    rescore_parser.add_argument("--config", required=True,
                                help="the scoring config to rescore with")
    rescore_parser.add_argument("--from", dest="from_date", default=None)
    rescore_parser.add_argument("--to", dest="to_date", default=None)
    arguments = parser.parse_args(argv)

    try:
        service_config = load_service_config(Path(arguments.service_config))
        if arguments.command == "open":
            record = open_day(service_config, date=arguments.date,
                              scoring_config_path=arguments.config)
            print(f"day {record.day} open")
            print(f"trial code {record.trial_code}")
            print(f"commitment {record.commitment}")
        elif arguments.command == "close":
            count = close_day(service_config, date=arguments.date)
            day = arguments.date or store.latest_day(
                Path(service_config.store_root))
            print(f"day {day} closed  trial_rows={count}")
        elif arguments.command == "reveal":
            record = reveal_day(service_config, date=arguments.date)
            print(f"day {record.day} revealed")
            print(f"target {record.target_id}")
            print(f"secret {record.secret}")
            print("check: printf '%s:%s' TARGET SECRET | sha256sum")
        elif arguments.command == "status":
            for line in day_status_lines(service_config):
                print(line)
        elif arguments.command == "rescore":
            counts = rescore_days(service_config,
                                  config_path=arguments.config,
                                  from_date=arguments.from_date,
                                  to_date=arguments.to_date)
            print("rescore "
                  + "  ".join(f"{name}={value}"
                              for name, value in sorted(counts.items())))
    except (ServiceConfigError, ConfigError, store.StoreError,
            ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
