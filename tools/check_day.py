"""Check that a beacon pulse after the close picked a day's target.

Spec VP1 section 3.5. A reader runs this with no trust in the operator:

    uv run python tools/check_day.py --reveal reveal.json
    uv run python tools/check_day.py --database starvector-public-<date>.sqlite
    uv run python tools/check_day.py --database <file> --fetch

It checks, for each vp1 day, that the randomness is the SHA-256 digest
of the pulse signature, that the target position follows from the
randomness, and that the target with its salt and proof gives the
committed pool root. With --fetch it also reads each pulse from two
drand relays and requires the same signature. The BLS signature check
needs the drand client (spec VP1 ruling D3).
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.beacon import DRAND_RELAYS, DrandRelays  # noqa: E402
from service.pick_rule import vp1_faults  # noqa: E402
from service.pulse import chain_named  # noqa: E402


def _days_from_reveal(path: Path) -> list[dict]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("protocol") != "vp1":
        raise SystemExit(f"{path}: not a vp1 day - nothing to check")
    return [{
        "day": value["day"], "target_id": value["target_id"],
        "signature": value["beacon_signature"],
        "randomness": value["randomness"],
        "target_index": value["target_index"],
        "target_salt": value["target_salt"],
        "target_proof": value["target_proof"],
        "pool_count": value["pool_count"], "pool_root": value["pool_root"],
        "beacon_chain": value["beacon_chain"],
        "beacon_round": value["beacon_round"]}]


def _days_from_database(path: Path) -> list[dict]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT day, target_id, beacon_signature, randomness, "
            "target_index, target_salt, target_proof, pool_image_count, "
            "pool_root, beacon_chain, beacon_round FROM days "
            "WHERE protocol = 'vp1' ORDER BY day").fetchall()
    return [{
        "day": row[0], "target_id": row[1], "signature": row[2],
        "randomness": row[3], "target_index": row[4], "target_salt": row[5],
        "target_proof": json.loads(row[6]), "pool_count": row[7],
        "pool_root": row[8], "beacon_chain": row[9], "beacon_round": row[10]}
        for row in rows]


def _fetch_faults(day: dict) -> list[str]:
    chain = chain_named(day["beacon_chain"])
    if chain.name != "drand-quicknet":
        return [f"day {day['day']}: the chain {chain.name!r} is not public"]
    answers = DrandRelays(relays=DRAND_RELAYS, chain=chain).answers(
        day["beacon_round"])
    if any(answer.get("signature") != day["signature"] for answer in answers):
        return [f"day {day['day']}: the relays give a different signature"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_day")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--reveal", type=Path)
    source.add_argument("--database", type=Path)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)
    days = _days_from_reveal(args.reveal) if args.reveal \
        else _days_from_database(args.database)
    faults = []
    for day in days:
        faults += vp1_faults(**{name: day[name] for name in (
            "day", "target_id", "signature", "randomness", "target_index",
            "target_salt", "target_proof", "pool_count", "pool_root")})
        if args.fetch:
            faults += _fetch_faults(day)
    for fault in faults:
        print(fault)
    print(f"{len(days)} vp1 day(s) checked, {len(faults)} fault(s)")
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
