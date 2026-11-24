"""Check that a beacon pulse after the send picked the target of an
instant trial.

Spec IM1 sections 5.2 and 10. A reader runs this with no trust in the
operator, on the saved answer of a public trial page:

    curl -o trial.json https://<site>/api/trial/<date>/<trial_id>
    uv run python tools/check_instant.py --trial trial.json
    uv run python tools/check_instant.py --trial trial.json --fetch

and on a snapshot of the public database, for each instant trial:

    uv run python tools/check_instant.py --database starvector-public-<date>.sqlite

It checks that the nonce agrees with the commitment of the receipt,
that the randomness is the SHA-256 digest of the pulse signature, that
the target position follows from the trial, the digest of the send, the
nonce, and the randomness, and that the target with its salt and proof
gives the committed pool root. It also checks that the pulse time is
after the time of the send. With --fetch it reads the pulse from two
drand relays and requires the same signature. The BLS signature check
needs the drand client (spec VP1 ruling D3).

With a database it also walks the chain of the sends (spec IM1 section
11): each send must name the chain value of the send before it, and
each chain value must be the digest of its row.
"""

import argparse
import datetime
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service import instant  # noqa: E402
from service.beacon import DRAND_RELAYS, DrandRelays  # noqa: E402
from service.pick_rule import instant_faults  # noqa: E402
from service.pulse import chain_named, pulse_time  # noqa: E402


def trial_from_answer(value: dict) -> dict:
    """The pick facts of one saved answer, by the names of the check.

    The answer is the body of GET /api/trial/<date>/<trial_id>, or the
    result that the owner of a trial gets. The two hold the same pick.
    """
    pick = value["pick"]
    return {
        "trial_id": value["trial_id"], "target_id": value["target_id"],
        "received_at": value["received_at"],
        "send_digest": pick["send_digest"],
        "commitment": pick["commitment"], "nonce": pick["nonce"],
        "signature": pick["beacon_signature"],
        "randomness": pick["randomness"],
        "target_index": pick["target_index"],
        "target_salt": pick["target_salt"],
        "target_proof": pick["target_proof"],
        "pool_count": pick["pool_count"], "pool_root": pick["pool_root"],
        "beacon_chain": pick["beacon_chain"],
        "beacon_round": pick["beacon_round"]}


def trials_from_database(path: Path) -> list[dict]:
    """The pick facts of each instant trial of one snapshot file."""
    names = ("trial_id", "target_id", "received_at", "send_digest",
             "commitment", "nonce", "beacon_signature", "randomness",
             "target_index", "target_salt", "target_proof",
             "pool_image_count", "pool_root", "beacon_chain",
             "beacon_round")
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            f"SELECT {', '.join(names)} FROM instant_trials "
            "ORDER BY chain_position").fetchall()
    found = []
    for row in rows:
        value = dict(zip(names, row))
        value["signature"] = value.pop("beacon_signature")
        value["pool_count"] = value.pop("pool_image_count")
        value["target_proof"] = json.loads(value["target_proof"])
        found.append(value)
    return found


def chain_faults_of_database(path: Path) -> list[str]:
    """The faults of the chain of the sends of one snapshot file."""
    with sqlite3.connect(path) as connection:
        rows = [instant.ChainRow(*row) for row in connection.execute(
            "SELECT chain_position, chain_previous, chain_link, trial_id, "
            "send_digest, commitment, received_at, beacon_round "
            "FROM instant_chain ORDER BY chain_position")]
    return instant.chain_faults(rows)


def time_faults(trial: dict) -> list[str]:
    """The pulse must come after the send (spec IM1 section 5.3)."""
    chain = chain_named(trial["beacon_chain"])
    sent = datetime.datetime.fromisoformat(trial["received_at"]).timestamp()
    if pulse_time(trial["beacon_round"], chain) <= sent:
        return [f"trial {trial['trial_id']}: the pulse is not after the "
                "send"]
    return []


def _fetch_faults(trial: dict) -> list[str]:
    chain = chain_named(trial["beacon_chain"])
    if chain.name != "drand-quicknet":
        return [f"trial {trial['trial_id']}: the chain {chain.name!r} is "
                "not public"]
    answers = DrandRelays(relays=DRAND_RELAYS, chain=chain).answers(
        trial["beacon_round"])
    if any(answer.get("signature") != trial["signature"]
           for answer in answers):
        return [f"trial {trial['trial_id']}: the relays give a different "
                "signature"]
    return []


def faults_of(trial: dict, *, fetch: bool = False) -> list[str]:
    """Each fault of one trial: the pick, the times, and the relays."""
    faults = instant_faults(**{name: trial[name] for name in (
        "trial_id", "send_digest", "commitment", "nonce", "signature",
        "randomness", "target_id", "target_index", "target_salt",
        "target_proof", "pool_count", "pool_root")})
    faults += time_faults(trial)
    if fetch:
        faults += _fetch_faults(trial)
    return faults


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_instant")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--trial", type=Path)
    source.add_argument("--database", type=Path)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args(argv)
    faults = []
    if args.trial:
        value = json.loads(args.trial.read_text(encoding="utf-8"))
        trials = [trial_from_answer(value)]
    else:
        trials = trials_from_database(args.database)
        faults += chain_faults_of_database(args.database)
    for trial in trials:
        faults += faults_of(trial, fetch=args.fetch)
    for fault in faults:
        print(fault)
    print(f"{len(trials)} instant trial(s) checked, {len(faults)} fault(s)")
    return 1 if faults else 0


if __name__ == "__main__":
    sys.exit(main())
