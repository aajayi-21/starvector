"""The public results database (spec R1).

A snapshot is one SQLite file that each person can read: the trials of
revealed days of a production pool, with the scores, the typed text,
and the sketch strokes. This module makes a snapshot from the store,
proves its fences again from the built files, and holds the operator's
commands for the withhold table and the anonymous identifiers.

The fences (spec R1 section 7), each one pinned by a test:

- I7: a day that is not revealed has no row.
- R13: a day of a development pool has no row.
- The pool stays closed: no image identifier that was not a target, no
  decoy, no element vocabulary, and no pick seed.
- No credential, no account text, and no device label.
- A withheld response has its scores and no text and no sketch.
- A player with no active record shows by an anonymous identifier.

The instant trials (spec IM1 section 13) are in tables of their own,
each with the prefix instant_. A trial is in when it has a result, its
pool is a production pool, and a public beacon picked its target. The
chain table holds each send of the store, with or without a result:
its rows hold digests alone, and a reader walks the full chain.

The store files stay the source of truth (CLAUDE.md I4). The build
reads the store and does not read the private index file, thus a stale
index cannot put a row of an earlier build in a public file. The build
writes nothing to the store.

Do not fit scoring weights on this data (I6). The README of each
snapshot says why, and nothing on the fit side imports this module.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.intake import IntakeError, validate_submission
from pipeline.config import intake_gates, load_scoring_config
from pipeline.context import PreparationRecord, load_preparation_record
from pool.preparation.config import load_preparation_config
from service import (credits, day_scores, guests, instant, instant_store,
                     notice, store)
from service.config import ServiceConfigError, load_service_config
from service.day import day_commitment
from service.pick_rule import instant_faults, vp1_faults
from service.pulse import chain_named, pulse_time
from service.index import _counts, _trial_files

SCHEMA_VERSION = 5
LICENSE_NAME = "CC BY 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"

_SCHEMA = """
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE players (
  player TEXT PRIMARY KEY,
  named INTEGER NOT NULL,
  first_day TEXT NOT NULL,
  trial_count INTEGER NOT NULL
);
CREATE TABLE days (
  day TEXT PRIMARY KEY,
  trial_code TEXT NOT NULL,
  target_id TEXT NOT NULL,
  protocol TEXT NOT NULL,
  commitment TEXT,
  secret TEXT,
  pool_root TEXT,
  beacon_chain TEXT,
  beacon_round INTEGER,
  round_time TEXT,
  beacon_signature TEXT,
  randomness TEXT,
  target_index INTEGER,
  target_salt TEXT,
  target_proof TEXT,
  opened_at TEXT NOT NULL,
  closed_at TEXT NOT NULL,
  revealed_at TEXT NOT NULL,
  scoring_config_hash TEXT NOT NULL,
  preparation_version_id TEXT NOT NULL,
  pool_label TEXT NOT NULL,
  pool_image_count INTEGER NOT NULL,
  player_count INTEGER NOT NULL,
  day_rank REAL
);
CREATE TABLE targets (
  target_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  page TEXT NOT NULL
);
CREATE TABLE configs (
  scoring_config_hash TEXT PRIMARY KEY,
  path TEXT NOT NULL,
  config_json TEXT NOT NULL,
  weights_json TEXT NOT NULL
);
CREATE TABLE submissions (
  day TEXT NOT NULL REFERENCES days (day),
  player TEXT NOT NULL REFERENCES players (player),
  received_at TEXT NOT NULL,
  started_at TEXT,
  seconds_from_start REAL,
  impression_count INTEGER NOT NULL,
  stroke_count INTEGER NOT NULL,
  group_count INTEGER NOT NULL,
  relation_count INTEGER NOT NULL,
  has_pasted_text INTEGER NOT NULL,
  withheld INTEGER NOT NULL,
  quarantined INTEGER NOT NULL,
  pasted_text TEXT,
  record_json TEXT,
  PRIMARY KEY (day, player)
);
CREATE TABLE impressions (
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  position INTEGER NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY (day, player, position)
);
CREATE TABLE strokes (
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  position INTEGER NOT NULL,
  group_id TEXT,
  color TEXT,
  point_count INTEGER NOT NULL,
  points_json TEXT NOT NULL,
  PRIMARY KEY (day, player, position)
);
CREATE TABLE groups (
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  group_id TEXT NOT NULL,
  label TEXT NOT NULL,
  PRIMARY KEY (day, player, group_id)
);
CREATE TABLE relations (
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  position INTEGER NOT NULL,
  relation TEXT NOT NULL,
  first_group TEXT NOT NULL,
  second_group TEXT NOT NULL,
  PRIMARY KEY (day, player, position)
);
CREATE TABLE trials (
  day TEXT NOT NULL REFERENCES days (day),
  player TEXT NOT NULL REFERENCES players (player),
  p REAL NOT NULL,
  target_rank INTEGER NOT NULL,
  decoy_count INTEGER NOT NULL,
  beaten INTEGER NOT NULL,
  tied INTEGER NOT NULL,
  scoring_config_hash TEXT NOT NULL,
  PRIMARY KEY (day, player)
);
CREATE TABLE trial_atoms (
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  position INTEGER NOT NULL,
  atom_text TEXT,
  element TEXT,
  weight REAL,
  similarity REAL,
  rarity REAL,
  PRIMARY KEY (day, player, position)
);
CREATE TABLE trial_channels (
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  channel TEXT NOT NULL,
  standardized REAL NOT NULL,
  p REAL NOT NULL,
  PRIMARY KEY (day, player, channel)
);
CREATE TABLE instant_owners (
  owner TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  named INTEGER NOT NULL,
  first_date TEXT NOT NULL,
  trial_count INTEGER NOT NULL
);
CREATE TABLE instant_chain (
  chain_position INTEGER PRIMARY KEY,
  trial_id TEXT NOT NULL UNIQUE,
  chain_previous TEXT NOT NULL,
  chain_link TEXT NOT NULL,
  send_digest TEXT NOT NULL,
  commitment TEXT NOT NULL,
  received_at TEXT NOT NULL,
  beacon_chain TEXT NOT NULL,
  beacon_round INTEGER NOT NULL,
  settled INTEGER NOT NULL
);
CREATE TABLE instant_trials (
  trial_id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  owner TEXT NOT NULL REFERENCES instant_owners (owner),
  trial_code TEXT NOT NULL,
  started_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  settled_at TEXT NOT NULL,
  seconds_from_start REAL NOT NULL,
  target_id TEXT NOT NULL,
  p REAL NOT NULL,
  target_rank INTEGER NOT NULL,
  decoy_count INTEGER NOT NULL,
  beaten INTEGER NOT NULL,
  tied INTEGER NOT NULL,
  scoring_config_hash TEXT NOT NULL,
  preparation_version_id TEXT NOT NULL,
  pool_label TEXT NOT NULL,
  pool_image_count INTEGER NOT NULL,
  pool_root TEXT NOT NULL,
  beacon_chain TEXT NOT NULL,
  beacon_round INTEGER NOT NULL,
  round_time TEXT NOT NULL,
  beacon_signature TEXT NOT NULL,
  randomness TEXT NOT NULL,
  nonce TEXT NOT NULL,
  commitment TEXT NOT NULL,
  send_digest TEXT NOT NULL,
  target_index INTEGER NOT NULL,
  target_salt TEXT NOT NULL,
  target_proof TEXT NOT NULL,
  chain_position INTEGER NOT NULL
);
CREATE TABLE instant_submissions (
  trial_id TEXT PRIMARY KEY REFERENCES instant_trials (trial_id),
  impression_count INTEGER NOT NULL,
  stroke_count INTEGER NOT NULL,
  group_count INTEGER NOT NULL,
  relation_count INTEGER NOT NULL,
  has_pasted_text INTEGER NOT NULL,
  withheld INTEGER NOT NULL,
  pasted_text TEXT,
  record_json TEXT
);
CREATE TABLE instant_impressions (
  trial_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY (trial_id, position)
);
CREATE TABLE instant_strokes (
  trial_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  group_id TEXT,
  color TEXT,
  point_count INTEGER NOT NULL,
  points_json TEXT NOT NULL,
  PRIMARY KEY (trial_id, position)
);
CREATE TABLE instant_groups (
  trial_id TEXT NOT NULL,
  group_id TEXT NOT NULL,
  label TEXT NOT NULL,
  PRIMARY KEY (trial_id, group_id)
);
CREATE TABLE instant_relations (
  trial_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  relation TEXT NOT NULL,
  first_group TEXT NOT NULL,
  second_group TEXT NOT NULL,
  PRIMARY KEY (trial_id, position)
);
CREATE TABLE instant_trial_atoms (
  trial_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  atom_text TEXT,
  element TEXT,
  weight REAL,
  similarity REAL,
  rarity REAL,
  PRIMARY KEY (trial_id, position)
);
CREATE TABLE instant_trial_channels (
  trial_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  standardized REAL NOT NULL,
  p REAL NOT NULL,
  PRIMARY KEY (trial_id, channel)
);
CREATE VIEW instant_owner_summary AS
  SELECT t.owner, COUNT(*) AS trial_count, AVG(t.p) AS mean_p,
         MIN(t.date) AS first_date, MAX(t.date) AS last_date
  FROM instant_trials AS t GROUP BY t.owner;
CREATE INDEX instant_trials_by_owner ON instant_trials (owner, chain_position);
CREATE VIEW trial_facts AS
  SELECT t.day, t.player, t.p, t.target_rank, t.decoy_count, t.beaten,
         t.tied, t.scoring_config_hash, d.trial_code, d.target_id,
         s.received_at, s.started_at, s.seconds_from_start,
         s.impression_count, s.stroke_count, s.group_count,
         s.relation_count, s.has_pasted_text, s.withheld
  FROM trials AS t
  JOIN days AS d ON d.day = t.day
  LEFT JOIN submissions AS s ON s.day = t.day AND s.player = t.player;
CREATE VIEW player_summary AS
  SELECT t.player, COUNT(*) AS trial_count, AVG(t.p) AS mean_p,
         MIN(t.day) AS first_day, MAX(t.day) AS last_day
  FROM trials AS t GROUP BY t.player;
CREATE INDEX trials_by_player ON trials (player, day);
"""

# Each table with its columns, in the sequence of the schema. The check
# command compares a built file against this.
_TABLES: dict[str, tuple[str, ...]] = {
    "meta": ("key", "value"),
    "players": ("player", "named", "first_day", "trial_count"),
    "days": ("day", "trial_code", "target_id", "protocol", "commitment",
             "secret", "pool_root", "beacon_chain", "beacon_round",
             "round_time", "beacon_signature", "randomness", "target_index",
             "target_salt", "target_proof", "opened_at", "closed_at",
             "revealed_at", "scoring_config_hash", "preparation_version_id",
             "pool_label", "pool_image_count", "player_count", "day_rank"),
    "targets": ("target_id", "source", "title", "page"),
    "configs": ("scoring_config_hash", "path", "config_json",
                "weights_json"),
    "submissions": ("day", "player", "received_at", "started_at",
                    "seconds_from_start", "impression_count", "stroke_count",
                    "group_count", "relation_count", "has_pasted_text",
                    "withheld", "quarantined", "pasted_text", "record_json"),
    "impressions": ("day", "player", "position", "text"),
    "strokes": ("day", "player", "position", "group_id", "color",
                "point_count", "points_json"),
    "groups": ("day", "player", "group_id", "label"),
    "relations": ("day", "player", "position", "relation", "first_group",
                  "second_group"),
    "trials": ("day", "player", "p", "target_rank", "decoy_count", "beaten",
               "tied", "scoring_config_hash"),
    "trial_atoms": ("day", "player", "position", "atom_text", "element",
                    "weight", "similarity", "rarity"),
    "trial_channels": ("day", "player", "channel", "standardized", "p"),
    "instant_owners": ("owner", "kind", "named", "first_date",
                       "trial_count"),
    "instant_chain": ("chain_position", "trial_id", "chain_previous",
                      "chain_link", "send_digest", "commitment",
                      "received_at", "beacon_chain", "beacon_round",
                      "settled"),
    "instant_trials": ("trial_id", "date", "owner", "trial_code",
                       "started_at", "received_at", "settled_at",
                       "seconds_from_start", "target_id", "p", "target_rank",
                       "decoy_count", "beaten", "tied", "scoring_config_hash",
                       "preparation_version_id", "pool_label",
                       "pool_image_count", "pool_root", "beacon_chain",
                       "beacon_round", "round_time", "beacon_signature",
                       "randomness", "nonce", "commitment", "send_digest",
                       "target_index", "target_salt", "target_proof",
                       "chain_position"),
    "instant_submissions": ("trial_id", "impression_count", "stroke_count",
                            "group_count", "relation_count",
                            "has_pasted_text", "withheld", "pasted_text",
                            "record_json"),
    "instant_impressions": ("trial_id", "position", "text"),
    "instant_strokes": ("trial_id", "position", "group_id", "color",
                        "point_count", "points_json"),
    "instant_groups": ("trial_id", "group_id", "label"),
    "instant_relations": ("trial_id", "position", "relation", "first_group",
                          "second_group"),
    "instant_trial_atoms": ("trial_id", "position", "atom_text", "element",
                            "weight", "similarity", "rarity"),
    "instant_trial_channels": ("trial_id", "channel", "standardized", "p"),
}

# The instant tables that hold rows of a response, with the count column
# of instant_submissions that each one must agree with.
_INSTANT_RESPONSE_TABLES = (("impression_count", "instant_impressions"),
                            ("stroke_count", "instant_strokes"),
                            ("group_count", "instant_groups"),
                            ("relation_count", "instant_relations"))

# Text that a public file must not hold: the marks of a credential and
# of the pool pick (spec R1 section 7).
_FORBIDDEN_TEXT = ("$argon2", "password_digest", "recovery_digest",
                   "operator_digest", "token_hash", "pick_seed")
_ANONYMOUS_RULE = re.compile(r"anon-[0-9a-f]{16}")
_SNAPSHOT_RULE = re.compile(r"starvector-public-\d{4}-\d{2}-\d{2}\.sqlite")


class PublicBuildError(RuntimeError):
    """A snapshot that the build or the check refuses, with the cause."""


@dataclass(frozen=True, slots=True)
class PublicDay:
    """One day that a snapshot holds, with the facts of its pool."""

    record: store.DayRecord
    preparation: PreparationRecord


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _preparation_of(record: store.DayRecord | instant_store.SendRecord,
                    ) -> PreparationRecord:
    """The preparation record that one day or one instant send names,
    checked.

    The record names its scoring config, and the config names the
    preparation record. Raises when one of them does not read or when
    the record is not the preparation of the day or of the send: a
    trial with a pool that the build cannot name is not a trial that
    the build can put in a public file.
    """
    where = f"day {record.day}" if isinstance(record, store.DayRecord) \
        else f"instant trial {record.trial_id}"
    try:
        config = load_scoring_config(Path(record.scoring_config_path))
        preparation = load_preparation_record(
            Path(config.input.preparation_record))
    except Exception as error:
        raise PublicBuildError(
            f"{where}: cannot read the preparation record of "
            f"{record.scoring_config_path}: {error}") from error
    if preparation.preparation_version_id != record.preparation_version_id:
        raise PublicBuildError(
            f"{where}: it names the preparation "
            f"{record.preparation_version_id[:8]} and its scoring config "
            f"names {preparation.preparation_version_id[:8]}")
    return preparation


# The beacon chains that a public pick can name (spec VP1 section 7). The
# fake chain of the tests and the development box is not one of them, so
# a day that it picked does not go public.
PUBLIC_CHAINS = ("drand-quicknet",)


def _day_faults(record: store.DayRecord) -> list[str]:
    """The faults of one revealed day, by its pick protocol."""
    if record.protocol == "vp1" and record.beacon_chain not in PUBLIC_CHAINS:
        return [f"day {record.day}: the beacon {record.beacon_chain!r} is "
                "not a public beacon"]
    if record.protocol != "vp1":
        if day_commitment(str(record.target_id), str(record.secret)) \
                != record.commitment:
            return [f"day {record.day}: the commitment does not agree "
                    "with the target and the secret"]
        return []
    return vp1_faults(
        day=record.day, target_id=str(record.target_id),
        signature=str(record.beacon_signature),
        randomness=str(record.pick_seed),
        target_index=int(record.target_index or 0),
        target_salt=str(record.target_salt),
        target_proof=record.target_proof or (),
        pool_count=int(record.pool_count or 0),
        pool_root=str(record.pool_root))


def _round_time(record: store.DayRecord) -> str | None:
    if record.protocol != "vp1" or record.beacon_chain is None \
            or record.beacon_round is None:
        return None
    moment = pulse_time(record.beacon_round, chain_named(record.beacon_chain))
    return datetime.datetime.fromtimestamp(
        moment, datetime.UTC).isoformat().replace("+00:00", "Z")


def _day_rank(data_root: Path, record: store.DayRecord,
              submissions: tuple[str, ...]) -> float | None:
    """The day rank of spec AG1 section 5, or None for a day with no send.

    A day with sends and no day-score file stops the build with the
    command that makes the file: a public file with a missing day rank
    is a check on a sample that nobody chose.
    """
    if not submissions:
        return None
    try:
        return day_scores.read_day_rank(data_root, record.day,
                                        record.scoring_config_hash)
    except day_scores.DayScoresError as error:
        raise PublicBuildError(str(error)) from error


def public_days(root: Path) -> list[PublicDay]:
    """The days that a snapshot holds (spec R1 section 5), ascending.

    A day is in when it is revealed and its pool is not a development
    pool. The commitment of each commit-v1 day is calculated again from
    its target and its secret, and each vp1 day gets the checks of spec
    VP1 section 3.5. A difference raises.
    """
    found = []
    for day in store.list_days(root):
        record = store.read_day_record(root, day)
        if record.status != "revealed":
            continue
        preparation = _preparation_of(record)
        if preparation.dev_only:
            continue
        faults = _day_faults(record)
        if faults:
            raise PublicBuildError("; ".join(faults))
        found.append(PublicDay(record=record, preparation=preparation))
    return found


@dataclass(frozen=True, slots=True)
class PublicInstant:
    """One instant trial that a snapshot holds, with its pool facts.

    owner is the store key that the trial counts for: the account, the
    account that claimed the guest of the trial, or a guest with no
    claim. The last field is the type of that owner.
    """

    date: str
    start: instant_store.StartRecord
    send: instant_store.SendRecord
    result: instant_store.ResultRecord
    preparation: PreparationRecord
    owner: str
    kind: str


def _instant_owner(root: Path,
                   start: instant_store.StartRecord) -> tuple[str, str]:
    """The owner that a trial counts for, and its type (spec IM1 7.4):
    the trials of a claimed guest are trials of the account."""
    if start.owner_kind == instant.GUEST:
        claim = guests.read_claim_or_none(root, start.owner)
        if claim is None:
            return start.owner, instant.GUEST
        return claim.player, instant.ACCOUNT
    return start.owner, instant.ACCOUNT


def _chain_row(send: instant_store.SendRecord) -> instant.ChainRow:
    return instant.ChainRow(
        position=send.chain_position, previous=send.chain_previous,
        digest=send.chain_link, trial_id=send.trial_id,
        send_digest=send.send_digest, commitment=send.commitment,
        received_at=send.received_at, beacon_round=send.beacon_round)


def instant_sends(root: Path) -> list[tuple[str, instant_store.SendRecord]]:
    """Each stored instant send with its date, in the sequence of the
    chain. A chain with a fault raises: a store with a removed or a
    changed send does not make a public file."""
    found = []
    for date in instant_store.list_dates(root):
        for trial_id in instant_store.list_trials(root, date):
            send = instant_store.read_send_or_none(root, date, trial_id)
            if send is not None:
                found.append((date, send))
    found.sort(key=lambda entry: entry[1].chain_position)
    faults = instant.chain_faults([_chain_row(send) for _, send in found])
    if faults:
        raise PublicBuildError("the chain of the instant sends: "
                               + faults[0])
    return found


def public_instant(root: Path) -> list[PublicInstant]:
    """The instant trials that a snapshot holds (spec IM1 section 13),
    in the sequence of the chain.

    A trial is in when it has a result, its pool is not a development
    pool, and a public beacon picked its target. The pick of each one
    is calculated again, and a difference raises.
    """
    found = []
    preparations: dict[str, PreparationRecord] = {}
    for date, send in instant_sends(root):
        result = instant_store.read_result_or_none(root, date, send.trial_id)
        start = instant_store.read_start_or_none(root, date, send.trial_id)
        if result is None:
            continue
        if start is None:
            raise PublicBuildError(
                f"instant trial {send.trial_id}: a result with no start")
        if send.scoring_config_path not in preparations:
            preparations[send.scoring_config_path] = _preparation_of(send)
        preparation = preparations[send.scoring_config_path]
        if preparation.dev_only or send.beacon_chain not in PUBLIC_CHAINS:
            continue
        faults = instant_faults(
            trial_id=send.trial_id, send_digest=send.send_digest,
            commitment=send.commitment, nonce=result.nonce,
            signature=result.beacon_signature, randomness=result.randomness,
            target_id=result.target_id, target_index=result.target_index,
            target_salt=result.target_salt,
            target_proof=result.target_proof, pool_count=send.pool_count,
            pool_root=send.pool_root)
        if faults:
            raise PublicBuildError("; ".join(faults))
        owner, kind = _instant_owner(root, start)
        found.append(PublicInstant(
            date=date, start=start, send=send, result=result,
            preparation=preparation, owner=owner, kind=kind))
    return found


def _needs_identifier(root: Path, player: str) -> bool:
    """A snapshot shows this player with no username: the record is
    revoked, or there is no record (spec R1 section 8)."""
    record = store.read_player_or_none(root, player)
    return record is None or record.status != "active"


def _players_of(root: Path, days: list[PublicDay],
                trials: list[PublicInstant] | None = None) -> list[str]:
    """Each account with a row in the snapshot: the players of the days,
    and the accounts of the instant trials. A guest is not an account."""
    names: set[str] = set()
    for day in days:
        names.update(store.list_submissions(root, day.record.day))
        names.update(player for player, pinned, _row
                     in _trial_files(root, day.record.day) if pinned)
    names.update(trial.owner for trial in trials or ()
                 if trial.kind == instant.ACCOUNT)
    return sorted(names)


def write_identifiers(root: Path, instant: datetime.datetime) -> list[str]:
    """Write the identifier record of each player that a snapshot shows
    with no username and that has none. Answers the players it wrote
    for."""
    written = []
    stamp = instant.astimezone(datetime.UTC).isoformat()
    for player in _players_of(root, public_days(root),
                              public_instant(root)):
        if _needs_identifier(root, player) \
                and store.read_identifier_or_none(root, player) is None:
            store.ensure_identifier(root, player, stamp)
            written.append(player)
    return written


def _public_names(root: Path, players: list[str]) -> dict[str, str]:
    """The name that the snapshot shows for each player."""
    names = {}
    for player in players:
        if not _needs_identifier(root, player):
            names[player] = player
            continue
        identifier = store.read_identifier_or_none(root, player)
        if identifier is None:
            raise PublicBuildError(
                f"player {player!r} has no active record and no identifier "
                "record - run python -m service.public identifiers")
        names[player] = identifier
    return names


def _seconds_between(started_at: str | None, received_at: str) -> float | None:
    if started_at is None:
        return None
    start = datetime.datetime.fromisoformat(started_at)
    end = datetime.datetime.fromisoformat(received_at)
    return (end - start).total_seconds()


def _credit_of(credit_cache: dict[str, dict], data_root: Path,
               preparation: PreparationRecord, target_id: str,
               where: str) -> dict:
    """The source page of one target, or a stop: a public file names
    where each of its photographs comes from."""
    release_path = preparation.pool_release_record_path
    if release_path not in credit_cache:
        credit_cache[release_path] = credits.load_credits(
            Path(release_path), data_root)
    credit = credit_cache[release_path].get(target_id)
    if credit is None:
        raise PublicBuildError(
            f"{where}: no source page for the target - the release "
            f"manifest of {release_path} must be below the data root")
    return credit


def _fill_instant(connection: sqlite3.Connection, root: Path,
                  data_root: Path, trials: list[PublicInstant],
                  names: dict[str, str],
                  credit_cache: dict[str, dict]) -> dict[str, int]:
    """Write the instant tables (spec IM1 section 13), and answer the
    facts for the meta table.

    The chain table gets each send of the store. Each other table gets
    the rows of the public trials alone.
    """
    public_ids = {trial.send.trial_id for trial in trials}
    sends = instant_sends(root)
    for _date, send in sends:
        connection.execute(
            "INSERT INTO instant_chain VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (send.chain_position, send.trial_id, send.chain_previous,
             send.chain_link, send.send_digest, send.commitment,
             send.received_at, send.beacon_chain, send.beacon_round,
             1 if send.trial_id in public_ids else 0))

    first_date: dict[str, str] = {}
    kinds: dict[str, str] = {}
    trial_count: dict[str, int] = {}
    withheld_count = 0
    gate_cache: dict[str, tuple] = {}
    for trial in trials:
        send, result, start = trial.send, trial.result, trial.start
        shown = names[trial.owner] if trial.kind == instant.ACCOUNT \
            else trial.owner
        first_date.setdefault(shown, trial.date)
        kinds[shown] = trial.kind
        trial_count[shown] = trial_count.get(shown, 0) + 1
        where = f"instant trial {send.trial_id}"
        credit = _credit_of(credit_cache, data_root, trial.preparation,
                            result.target_id, where)
        connection.execute(
            "INSERT OR IGNORE INTO targets VALUES (?, ?, ?, ?)",
            (result.target_id, credit["source"], credit["title"],
             credit["page"]))
        config_path = Path(send.scoring_config_path)
        config_text = config_path.read_text(encoding="utf-8")
        connection.execute(
            "INSERT OR IGNORE INTO configs VALUES (?, ?, ?, ?)",
            (send.scoring_config_hash, send.scoring_config_path, config_text,
             _json(json.loads(config_text)["fusion"]["weights"])))
        if send.scoring_config_path not in gate_cache:
            gate_cache[send.scoring_config_path] = (
                intake_gates(load_scoring_config(config_path)),
                load_preparation_config(
                    Path(trial.preparation.config_path)).linedraw.canvas_px)
        gates, canvas_px = gate_cache[send.scoring_config_path]
        wire = send.record
        try:
            validate_submission(wire, gates, canvas_px)
        except (IntakeError, ValueError) as error:
            raise PublicBuildError(
                f"{where}: Layer 0 does not read the send: {error}"
                ) from error
        row = result.row
        moment = pulse_time(send.beacon_round,
                            chain_named(send.beacon_chain))
        connection.execute(
            "INSERT INTO instant_trials VALUES ("
            + ", ".join("?" * 31) + ")",
            (send.trial_id, trial.date, shown, start.trial_code,
             start.started_at, send.received_at, result.settled_at,
             _seconds_between(start.started_at, send.received_at),
             result.target_id, float(row["p"]), int(row["target_rank"]),
             int(row["decoy_count"]), int(row["beaten"]), int(row["tied"]),
             send.scoring_config_hash, send.preparation_version_id,
             trial.preparation.pool_label, send.pool_count, send.pool_root,
             send.beacon_chain, send.beacon_round,
             datetime.datetime.fromtimestamp(moment, datetime.UTC)
             .isoformat().replace("+00:00", "Z"),
             result.beacon_signature, result.randomness, result.nonce,
             send.commitment, send.send_digest, result.target_index,
             result.target_salt, json.dumps(list(result.target_proof)),
             send.chain_position))
        withheld = instant_store.read_withheld_or_none(
            root, trial.date, send.trial_id) is not None
        counts = _counts(wire)
        connection.execute(
            "INSERT INTO instant_submissions VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (send.trial_id, *counts, 1 if withheld else 0,
             None if withheld or not counts[4] else wire.get("pasted_text"),
             None if withheld else _json(wire)))
        for position, atom in enumerate(row.get("report") or []):
            connection.execute(
                "INSERT INTO instant_trial_atoms VALUES "
                "(?, ?, ?, ?, ?, ?, ?)",
                (send.trial_id, position,
                 None if withheld else atom.get("atom_text"),
                 atom.get("element"), atom.get("weight"),
                 atom.get("similarity"), atom.get("rarity")))
        for channel, value in (row.get("channel_scores") or {}).items():
            connection.execute(
                "INSERT INTO instant_trial_channels VALUES (?, ?, ?, ?)",
                (send.trial_id, channel, float(value["standardized"]),
                 float(value["p"])))
        if withheld:
            withheld_count += 1
            continue
        for position, text in enumerate(wire.get("impressions") or []):
            connection.execute(
                "INSERT INTO instant_impressions VALUES (?, ?, ?)",
                (send.trial_id, position, text))
        for position, stroke in enumerate(wire.get("canvas_strokes") or []):
            points = stroke["points"]
            connection.execute(
                "INSERT INTO instant_strokes VALUES (?, ?, ?, ?, ?, ?)",
                (send.trial_id, position, stroke.get("group_id"),
                 stroke.get("color"), len(points), _json(points)))
        for group in wire.get("groups") or []:
            connection.execute(
                "INSERT INTO instant_groups VALUES (?, ?, ?)",
                (send.trial_id, group["id"], group["label"]))
        for position, relation in enumerate(wire.get("relations") or []):
            connection.execute(
                "INSERT INTO instant_relations VALUES (?, ?, ?, ?, ?)",
                (send.trial_id, position, relation["relation"],
                 relation["of"][0], relation["of"][1]))
    for shown in sorted(first_date):
        named = kinds[shown] == instant.ACCOUNT \
            and not _ANONYMOUS_RULE.fullmatch(shown)
        connection.execute(
            "INSERT INTO instant_owners VALUES (?, ?, ?, ?, ?)",
            (shown, kinds[shown], 1 if named else 0, first_date[shown],
             trial_count[shown]))
    return {"instant_trial_count": len(trials),
            "instant_send_count": len(sends),
            "instant_withheld_count": withheld_count}


def _fill(connection: sqlite3.Connection, root: Path, data_root: Path,
          days: list[PublicDay],
          trials: list[PublicInstant] | None = None) -> dict[str, int]:
    """Write each public row, and answer the facts for the meta table."""
    trials = trials or []
    names = _public_names(root, _players_of(root, days, trials))
    credit_cache: dict[str, dict] = {}
    gate_cache: dict[str, tuple] = {}
    first_day: dict[str, str] = {}
    trial_count: dict[str, int] = {}
    withheld_count = 0

    for day in days:
        record = day.record
        name = record.day
        submissions = store.list_submissions(root, name)
        vp1 = record.protocol == "vp1"
        connection.execute(
            "INSERT INTO days VALUES (" + ", ".join("?" * 24) + ")",
            (name, record.trial_code, record.target_id, record.protocol,
             record.commitment, record.secret, record.pool_root,
             record.beacon_chain, record.beacon_round, _round_time(record),
             record.beacon_signature, record.pick_seed if vp1 else None,
             record.target_index, record.target_salt,
             json.dumps(list(record.target_proof))
             if record.target_proof is not None else None,
             record.opened_at, record.closed_at,
             record.revealed_at, record.scoring_config_hash,
             record.preparation_version_id, day.preparation.pool_label,
             day.preparation.image_count, len(submissions),
             _day_rank(data_root, record, submissions)))

        release_path = day.preparation.pool_release_record_path
        if release_path not in credit_cache:
            credit_cache[release_path] = credits.load_credits(
                Path(release_path), data_root)
        credit = credit_cache[release_path].get(record.target_id)
        if credit is None:
            raise PublicBuildError(
                f"day {name}: no source page for the target - the release "
                f"manifest of {release_path} must be below the data root")
        connection.execute(
            "INSERT OR IGNORE INTO targets VALUES (?, ?, ?, ?)",
            (record.target_id, credit["source"], credit["title"],
             credit["page"]))

        config_path = Path(record.scoring_config_path)
        config_text = config_path.read_text(encoding="utf-8")
        weights = json.loads(config_text)["fusion"]["weights"]
        connection.execute(
            "INSERT OR IGNORE INTO configs VALUES (?, ?, ?, ?)",
            (record.scoring_config_hash, record.scoring_config_path,
             config_text, _json(weights)))
        if record.scoring_config_path not in gate_cache:
            gate_cache[record.scoring_config_path] = (
                intake_gates(load_scoring_config(config_path)),
                load_preparation_config(
                    Path(day.preparation.config_path)).linedraw.canvas_px)
        gates, canvas_px = gate_cache[record.scoring_config_path]

        withheld_players = set()
        for player in submissions:
            stored = store.read_json_or_none(
                store.submission_path(root, name, player))
            if stored is None or not isinstance(stored.get("record"), dict):
                raise PublicBuildError(
                    f"day {name}: the submission of {player} does not parse")
            wire = stored["record"]
            try:
                validate_submission(wire, gates, canvas_px)
            except (IntakeError, ValueError) as error:
                raise PublicBuildError(
                    f"day {name}: Layer 0 does not read the submission of "
                    f"{player}: {error}") from error
            shown = names[player]
            first_day.setdefault(shown, name)
            withheld = store.read_withheld_or_none(root, name,
                                                   player) is not None
            started_at = store.read_start_or_none(root, name, player)
            received_at = str(stored["received_at"])
            counts = _counts(wire)
            pasted = wire.get("pasted_text")
            quarantined = store.read_quarantine_or_none(
                root, name, player) is not None
            connection.execute(
                "INSERT INTO submissions VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name, shown, received_at, started_at,
                 _seconds_between(started_at, received_at), *counts,
                 1 if withheld else 0, 1 if quarantined else 0,
                 None if withheld or not counts[4] else pasted,
                 None if withheld else _json(wire)))
            if withheld:
                withheld_players.add(player)
                withheld_count += 1
                continue
            for position, text in enumerate(wire.get("impressions") or []):
                connection.execute(
                    "INSERT INTO impressions VALUES (?, ?, ?, ?)",
                    (name, shown, position, text))
            for position, stroke in enumerate(
                    wire.get("canvas_strokes") or []):
                points = stroke["points"]
                connection.execute(
                    "INSERT INTO strokes VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (name, shown, position, stroke.get("group_id"),
                     stroke.get("color"), len(points), _json(points)))
            for group in wire.get("groups") or []:
                connection.execute(
                    "INSERT INTO groups VALUES (?, ?, ?, ?)",
                    (name, shown, group["id"], group["label"]))
            for position, relation in enumerate(wire.get("relations") or []):
                connection.execute(
                    "INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?)",
                    (name, shown, position, relation["relation"],
                     relation["of"][0], relation["of"][1]))

        for player, pinned, row in _trial_files(root, name):
            if not pinned:
                continue
            shown = names[player]
            first_day.setdefault(shown, name)
            trial_count[shown] = trial_count.get(shown, 0) + 1
            connection.execute(
                "INSERT INTO trials VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, shown, float(row["p"]), int(row["target_rank"]),
                 int(row["decoy_count"]), int(row["beaten"]),
                 int(row["tied"]), str(row["scoring_config_hash"])))
            hidden = player in withheld_players
            for position, atom in enumerate(row.get("report") or []):
                connection.execute(
                    "INSERT INTO trial_atoms VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, shown, position,
                     None if hidden else atom.get("atom_text"),
                     atom.get("element"), atom.get("weight"),
                     atom.get("similarity"), atom.get("rarity")))
            for channel, value in (row.get("channel_scores") or {}).items():
                connection.execute(
                    "INSERT INTO trial_channels VALUES (?, ?, ?, ?, ?)",
                    (name, shown, channel, float(value["standardized"]),
                     float(value["p"])))

    for shown in sorted(first_day):
        connection.execute(
            "INSERT INTO players VALUES (?, ?, ?, ?)",
            (shown, 0 if _ANONYMOUS_RULE.fullmatch(shown) else 1,
             first_day[shown], trial_count.get(shown, 0)))
    return {"withheld_count": withheld_count,
            **_fill_instant(connection, root, data_root, trials, names,
                            credit_cache)}


def code_version() -> str:
    """The commit of the working tree, or "unknown" with no git."""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"],
                                capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {table: connection.execute(
        f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in _TABLES if table != "meta"}


def build(root: Path, data_root: Path, out_dir: Path, *,
          snapshot_date: str, built_at: str,
          version: str = "unknown") -> Path:
    """Make one snapshot directory, and answer the path of its database.

    The database lands in a temporary file and os.replace puts it in
    position, thus a reader does not see a half-built file. The same
    store gives the same rows. built_at and version are in meta alone.

    Raises PublicBuildError and writes no database when a fence does
    not hold (spec R1 section 12): a day with no readable preparation
    record, a commitment that does not agree, a response that Layer 0
    does not read, a target with no source page, or a player with no
    identifier record.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", snapshot_date):
        raise PublicBuildError(
            f"the snapshot date must be YYYY-MM-DD, got {snapshot_date!r}")
    days = public_days(root)
    trials = public_instant(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"starvector-public-{snapshot_date}.sqlite"
    handle, temporary = tempfile.mkstemp(dir=out_dir, suffix=".tmp")
    os.close(handle)
    os.unlink(temporary)
    try:
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(_SCHEMA)
            facts = _fill(connection, root, data_root, days, trials)
            counts = _row_counts(connection)
            meta = {
                "schema_version": str(SCHEMA_VERSION),
                "snapshot_date": snapshot_date,
                "built_at": built_at,
                "code_version": version,
                "license": LICENSE_NAME,
                "license_url": LICENSE_URL,
                "notice_version": str(notice.NOTICE_VERSION),
                "first_day": days[0].record.day if days else "",
                "last_day": days[-1].record.day if days else "",
                "day_count": str(len(days)),
                "withheld_count": str(facts["withheld_count"]),
                "instant_trial_count": str(facts["instant_trial_count"]),
                "instant_send_count": str(facts["instant_send_count"]),
                "instant_withheld_count":
                    str(facts["instant_withheld_count"]),
                **{f"rows_{table}": str(count)
                   for table, count in counts.items()},
            }
            connection.executemany("INSERT INTO meta VALUES (?, ?)",
                                   sorted(meta.items()))
            connection.commit()
        finally:
            connection.close()
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    (out_dir / "README.md").write_text(
        readme_text(meta, counts), encoding="utf-8")
    (out_dir / "LICENSE.txt").write_text(_LICENSE_TEXT, encoding="utf-8")
    release = {
        "snapshot_date": snapshot_date, "schema_version": SCHEMA_VERSION,
        "code_version": version, "built_at": built_at,
        "license": LICENSE_NAME, "first_day": meta["first_day"],
        "last_day": meta["last_day"], "day_count": len(days),
        "withheld_count": facts["withheld_count"],
        "instant_trial_count": facts["instant_trial_count"],
        "instant_send_count": facts["instant_send_count"],
        "instant_withheld_count": facts["instant_withheld_count"],
        "rows": counts,
    }
    (out_dir / "release.json").write_text(
        json.dumps(release, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    sums = []
    for name in (target.name, "README.md", "LICENSE.txt", "release.json"):
        digest = hashlib.sha256((out_dir / name).read_bytes()).hexdigest()
        sums.append(f"{digest}  {name}\n")
    (out_dir / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    return target


_LICENSE_TEXT = f"""\
Starvector public results database

The responses and the scores in this snapshot are licensed under the
Creative Commons Attribution 4.0 International license ({LICENSE_NAME}).
{LICENSE_URL}

You can copy, share, and adapt this data for each purpose. Give credit
to the Starvector project, name the snapshot date, and say if you
changed the data.

The photographs are not in this snapshot and are not under this
license. Each target photograph has its own author and its own
license, which are named at its source page: the "page" column of the
"targets" table.
"""

# The example queries of the README. A test runs each one against a
# built snapshot.
README_EXAMPLES: tuple[tuple[str, str], ...] = (
    ("How many days, players, and trials are in this snapshot?",
     "SELECT (SELECT COUNT(*) FROM days) AS days,\n"
     "       (SELECT COUNT(*) FROM players) AS players,\n"
     "       (SELECT COUNT(*) FROM trials) AS trials;"),
    ("The mean trial score of each day. With no information the "
     "expected value is 0.5.",
     "SELECT day, COUNT(*) AS trials, ROUND(AVG(p), 4) AS mean_p\n"
     "FROM trials GROUP BY day ORDER BY day;"),
    ("The players with 30 trials or more, by mean trial score.",
     "SELECT player, trial_count, ROUND(mean_p, 4) AS mean_p\n"
     "FROM player_summary WHERE trial_count >= 30\n"
     "ORDER BY mean_p DESC;"),
    ("Each typed impression of one day, with the score of its trial.",
     "SELECT i.player, i.position, i.text, t.p\n"
     "FROM impressions AS i\n"
     "JOIN trials AS t ON t.day = i.day AND t.player = i.player\n"
     "WHERE i.day = (SELECT MAX(day) FROM days)\n"
     "ORDER BY i.player, i.position;"),
    ("Does time on a trial go with the score?",
     "SELECT CAST(seconds_from_start / 60 AS INTEGER) AS minutes,\n"
     "       COUNT(*) AS trials, ROUND(AVG(p), 4) AS mean_p\n"
     "FROM trial_facts WHERE seconds_from_start IS NOT NULL\n"
     "GROUP BY minutes ORDER BY minutes;"),
    ("The words that connected most often with an element of the target.",
     "SELECT element, COUNT(*) AS uses, ROUND(AVG(similarity), 3) "
     "AS mean_similarity\n"
     "FROM trial_atoms WHERE element IS NOT NULL\n"
     "GROUP BY element ORDER BY uses DESC LIMIT 20;"),
    ("Check that the target of each commit-v1 day was fixed before the "
     "play: the commitment is the SHA-256 of the target, a colon, and the "
     "secret. This query lists the three values, and a script calculates "
     "the digest.",
     "SELECT day, target_id, secret, commitment FROM days\n"
     "WHERE protocol = 'commit-v1' ORDER BY day;"),
    ("Check that a beacon pulse after the close picked the target of each "
     "vp1 day: `uv run python tools/check_day.py --database <file>` does "
     "it for each such day.",
     "SELECT day, beacon_round, round_time, randomness, target_index,\n"
     "       pool_image_count, pool_root FROM days\n"
     "WHERE protocol = 'vp1' ORDER BY day;"),
    ("The instant record of each owner: the count and the mean of each "
     "trial with a result. With no information the expected mean is 0.5.",
     "SELECT o.owner, o.kind, s.trial_count, ROUND(s.mean_p, 4) AS mean_p\n"
     "FROM instant_owner_summary AS s\n"
     "JOIN instant_owners AS o ON o.owner = s.owner\n"
     "ORDER BY s.trial_count DESC;"),
    ("The mean of all the instant trials, by the number of the trial in "
     "the record of its owner. A selected result does not show here: "
     "each trial is in.",
     "SELECT n, COUNT(*) AS trials, ROUND(AVG(p), 4) AS mean_p FROM (\n"
     "  SELECT p, ROW_NUMBER() OVER (PARTITION BY owner\n"
     "                               ORDER BY chain_position) AS n\n"
     "  FROM instant_trials)\n"
     "GROUP BY n ORDER BY n;"),
    ("Check the chain of the instant sends and the pick of each instant "
     "trial: `uv run python tools/check_instant.py --database <file>` "
     "does it. This query shows that the pulse of each trial came after "
     "its send.",
     "SELECT trial_id, received_at, round_time, beacon_round\n"
     "FROM instant_trials ORDER BY chain_position;"),
)


def readme_text(meta: dict[str, str], counts: dict[str, int]) -> str:
    """The README of one snapshot: what each table means, the rules of
    what is in and what is not, the license, and the example queries."""
    examples = "\n".join(
        f"**{question}**\n\n```sql\n{query}\n```\n"
        for question, query in README_EXAMPLES)
    rows = "\n".join(f"| `{table}` | {count} |"
                     for table, count in counts.items())
    return f"""\
# Starvector public results database

Snapshot date: {meta["snapshot_date"]}. Schema version:
{meta["schema_version"]}. Days: {meta["day_count"]}, from
{meta["first_day"] or "none"} to {meta["last_day"] or "none"}.
Withheld responses: {meta["withheld_count"]}. Instant trials:
{meta["instant_trial_count"]} of {meta["instant_send_count"]} sends,
with {meta["instant_withheld_count"]} withheld.

Starvector is a daily game. Each day one photograph, the target, is
hidden. A player sees a short code alone and sends typed impressions,
a sketch, or the two. When the day closes, the system ranks the target
against each other photograph of a fixed pool, and the trial score `p`
is the fraction of those other photographs that the target beat. With
no information the target is equally likely at each position, thus the
expected value of `p` is 0.5 by construction.

This file is one SQLite database. `sqlite3`, DuckDB, Python, and R read
it with no other tool.

## What is in the file

A trial is in the file when its day is revealed, the day is a day of a
production pool, and the trial row is the one that the day published.
An instant trial is in the file when it has a result, its pool is a
production pool, and the public beacon picked its target.
No other rule removes a trial: a player with one trial is in the file,
and so is a player below the floors of the game's boards.

| Table | Rows |
|---|---|
{rows}

| Table | One row is | Columns of note |
|---|---|---|
| `meta` | a fact of this snapshot | `key`, `value` |
| `players` | a player with a response in the file | `player` is the username. `named` is 0 for a player whose account is gone: `player` is then an anonymous identifier, the same one in each snapshot |
| `days` | a revealed day | `trial_code` is what the players saw. `target_id` names the photograph. `protocol` says how the target was picked: see below |
| `targets` | the photograph of a revealed day | `page` is the source page, where the author and the license are named |
| `configs` | the scoring configuration of a day | `config_json` is the full configuration text, and `weights_json` its channel weights |
| `submissions` | a response | `received_at` and `started_at` are UTC times. `seconds_from_start` is the time from the first opening of the drawing screen to the send. `record_json` is the raw response |
| `impressions` | one typed impression of a response | `position`, `text` |
| `strokes` | one sketch stroke | `points_json` is the point sequence, each point an x and a y from 0 to 1. A stroke has no time |
| `groups` | one labeled group of strokes | `group_id`, `label` |
| `relations` | one stated relation of two groups | `relation`, `first_group`, `second_group` |
| `trials` | a trial score | `p`, `target_rank`, `decoy_count`, `beaten`, `tied`. The skill numbers read a corrected score: see below |
| `trial_atoms` | one atom of a trial report | the typed text, the element of the target that it agreed with most, and three numbers |
| `trial_channels` | one channel of a trial | the standardized score at the target, and the trial score of that channel alone |

| `instant_owners` | an owner of an instant trial in the file | `kind` is `account` or `guest`. `named` is 0 for a guest and for an account that is gone |
| `instant_chain` | one instant send of the store | each send, with or without a result. The row holds digests alone. `settled` is 1 for a send with a trial in this file |
| `instant_trials` | an instant trial with a result | the owner, the times, the target, the trial score, and the pick: see below |
| `instant_submissions` | the response of an instant trial | as `submissions`, with `trial_id` as the key |
| `instant_impressions`, `instant_strokes`, `instant_groups`, `instant_relations` | the parts of an instant response | as the four tables of a daily response |
| `instant_trial_atoms`, `instant_trial_channels` | the report of an instant trial | as the two tables of a daily trial |

Three views: `trial_facts` is one row for each trial with the day and
the response facts, `player_summary` is one row for each player, and
`instant_owner_summary` is one row for each owner of an instant trial.

**The instant trial.** An instant trial has no day. A player sends a
response, and a pulse of the drand quicknet beacon a few seconds after
the send picks a target for that one response. The daily tables hold no
instant trial, and no board and no skill number of the game reads one.
A guest plays with no account: `instant_owners.owner` is then an
identifier that starts with `guest-`. A guest who makes an account is in
the file as that account.

**The pick of an instant trial.** `commitment` is the SHA-256 of the
text `instant-nonce:`, `trial_id`, a colon, and `nonce`. The player gets
`commitment` with the receipt of the send, before the pulse, and the
`nonce` with the result. `randomness` is the SHA-256 of
`beacon_signature`. `target_index` is the first 16 hex characters of
SHA-256(`instant-target:` trial_id `:` send_digest `:` nonce `:`
randomness) as a number, modulo `pool_image_count`. `send_digest` is the
SHA-256 of the canonical JSON of the response, and `target_salt` with
`target_proof` takes `target_id` up to `pool_root`. `round_time` is
after `received_at`.

**The chain of the instant sends.** Each send holds the digest of the
send before it: `chain_link` is the SHA-256 of the text
`instant-chain:`, `chain_previous`, `trial_id`, `send_digest`,
`commitment`, `received_at`, and `beacon_round`, with a colon between
each two. The first send has 64 zeros in `chain_previous`. A send that
is removed, added, or changed after a snapshot does not agree with the
`chain_link` values of that snapshot.
`uv run python tools/check_instant.py --database <file>` walks the chain
and checks each pick.

**Read the instant trials as one set.** A player has more than one
instant trial on a date, and a player picks which result to show. One
high trial is thus not evidence. `instant_trials` holds each trial with
a result, and no owner can remove one.

**The start time.** `started_at` is the server's time when the player
first opened the drawing screen of that day. It is not the first sight
of the day's code and not the first stroke. A response of an earlier
build of the game has NULL there.

**The commitment (`protocol` is `commit-v1`).** When such a day opens,
the server publishes `commitment`, the SHA-256 digest of the text
`target_id`, a colon, and `secret`. The target and the secret are not
public before the reveal. Calculate the digest again from the two
columns: it shows that the target did not change after the play.

**The pick after the close (`protocol` is `vp1`).** Such a day has no
target during the play. When it opens, the server names `beacon_round`,
a pulse of the drand quicknet beacon a minute after the close, and the
`pool_root` of a pool committed in the public repository before the
open. After the close, the pulse picks the target:
`randomness` is the SHA-256 of `beacon_signature`, `target_index` is the
first 16 hex characters of SHA-256(`day-target:` day `:` randomness) as
a number, modulo `pool_image_count`, and `target_salt` with
`target_proof` takes `target_id` up to `pool_root`.
`uv run python tools/check_day.py --database <file>` does these checks,
and `--fetch` also reads the pulse from two drand relays.

**The corrected score and the skill numbers.** `p` is the share of the
decoys beaten, with half a decoy for each equal score. The skill numbers
read a corrected score that never reaches 0 or 1:
`(beaten + 0.5 × tied + 0.5) / (decoy_count + 1)`. For one player's n
trials, `S` is the sum of `-log(corrected)` and `T` the sum of
`-log(1 - corrected)`. The skill number is `(n - 1) / S` and the hit
number is `T / n`. Each is 1.0 at chance. With no skill, `2S` and `2T`
follow a chi-squared law at `2n` degrees of freedom. The evidence value
is two times the smaller of the bottom tail of `2S` and the top tail of
`2T`, at most 1.

**The day rank.** `day_rank` asks if the players of a day beat chance
together, and it holds when their scores move together. For each image
of the pool, it takes the mean corrected score that the day's players
get with that image as the target. `day_rank` is the position of the
real target's mean among those means, from 0 to 1, with half a position
for each equal mean. With no skill it is flat on 0 to 1, because the
target is an equally likely image of the pool. A day with no response
has NULL.

**A quarantined response.** A response that the model server refused
on each retry at the close has `quarantined` 1 and no row in `trials`:
the close did not give it a score. The response itself is in the file.

**A withheld response.** The operator can withhold the text and the
sketch of a response that must not be public. Its row has `withheld` 1
and NULL in `record_json` and `pasted_text`, it has no row in the four
tables after `submissions`, and its `trial_atoms` rows have NULL in
`atom_text`. Its scores and its counts are in the file.

## What is not in the file

- A day that is not revealed, and a day of a development pool.
- An instant trial with no result, and one of a development pool. Its
  row in `instant_chain` is in the file, with no response and no
  target.
- The pool: the photographs that were not a target, the photographs
  that a target was ranked against, and the element vocabulary. A
  reader with the pool knows each possible target of a subsequent day.
- The photographs themselves. `targets.page` points at each one.
- Passwords, recovery codes, sessions, and each other credential.
- The account text and the picture of a player.
- A client address and a device name. The game does not store an
  address.

## Do not tune a scorer on this data

If the players have no ability, this data holds no signal. It does
hold a noise optimum, and an optimizer finds it. A scoring rule that
is fitted on the true targets of these trials thus shows ability that
is not there. The game's own weights come from data where the
correspondence is known by construction, and not from this file. Use
this data to read what happened.

## Example queries

{examples}
## License

The responses and the scores: {LICENSE_NAME}, {LICENSE_URL}. Give
credit to the Starvector project and name the snapshot date. Each
photograph has its own license at its source page. `LICENSE.txt` has
the text.
"""


def _snapshot_file(directory: Path) -> Path:
    found = sorted(path for path in directory.iterdir()
                   if _SNAPSHOT_RULE.fullmatch(path.name))
    if len(found) != 1:
        raise PublicBuildError(
            f"{directory}: expected one starvector-public-<date>.sqlite, "
            f"found {len(found)}")
    return found[0]


def check(directory: Path) -> list[str]:
    """Prove the fences of one built snapshot again, from its files
    alone. Answers the faults, and an empty answer is a clean
    snapshot.

    The check reads the files that a reader gets. It thus finds a
    fault that a change of the build puts in, and a file that a person
    edited after the build.
    """
    faults: list[str] = []
    target = _snapshot_file(directory)
    sums_path = directory / "SHA256SUMS"
    if not sums_path.is_file():
        faults.append("SHA256SUMS is not there")
    else:
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            digest, _space, name = line.partition("  ")
            path = directory / name
            if not path.is_file():
                faults.append(f"SHA256SUMS names {name}, which is not there")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                faults.append(f"the digest of {name} does not agree")

    raw = target.read_bytes()
    for text in _FORBIDDEN_TEXT:
        if text.encode("utf-8") in raw:
            faults.append(f"the file holds the text {text!r}")

    connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if tables != set(_TABLES):
            faults.append(f"the tables are {sorted(tables)}")
            return faults
        columns_agree = True
        for table, columns in _TABLES.items():
            found = tuple(row[1] for row in connection.execute(
                f"PRAGMA table_info({table})"))
            if found != columns:
                columns_agree = False
                faults.append(f"the columns of {table} are {found}")
        if not columns_agree:
            # The checks after this one name columns of the schema.
            return faults
        meta = dict(connection.execute("SELECT key, value FROM meta"))
        if meta.get("schema_version") != str(SCHEMA_VERSION):
            faults.append("meta.schema_version is not "
                          f"{SCHEMA_VERSION}")

        for (day, target_id, protocol, secret, commitment, label, signature,
             randomness, index, salt, proof, count, root) in connection.execute(
                "SELECT day, target_id, protocol, secret, commitment, "
                "pool_label, beacon_signature, randomness, target_index, "
                "target_salt, target_proof, pool_image_count, pool_root "
                "FROM days"):
            if protocol == "vp1":
                faults.extend(vp1_faults(
                    day=day, target_id=target_id, signature=signature or "",
                    randomness=randomness or "", target_index=index or 0,
                    target_salt=salt or "",
                    target_proof=json.loads(proof or "[]"),
                    pool_count=count, pool_root=root or ""))
            elif day_commitment(target_id, secret) != commitment:
                faults.append(f"day {day}: the commitment does not agree")
            if label.startswith("dev-"):
                faults.append(f"day {day}: a day of a development pool")
        for table in ("submissions", "trials", "impressions", "strokes",
                      "groups", "relations", "trial_atoms",
                      "trial_channels"):
            orphans = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE day NOT IN "
                "(SELECT day FROM days)").fetchone()[0]
            if orphans:
                faults.append(f"{table}: {orphans} row(s) of a day that is "
                              "not in days")
            strangers = connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE player NOT IN "
                "(SELECT player FROM players)").fetchone()[0]
            if strangers:
                faults.append(f"{table}: {strangers} row(s) of a player "
                              "that is not in players")
        if connection.execute(
                "SELECT COUNT(*) FROM days WHERE target_id NOT IN "
                "(SELECT target_id FROM targets)").fetchone()[0]:
            faults.append("days: a target with no row in targets")
        if connection.execute(
                "SELECT COUNT(*) FROM instant_trials WHERE target_id NOT IN "
                "(SELECT target_id FROM targets)").fetchone()[0]:
            faults.append("instant_trials: a target with no row in targets")
        if connection.execute(
                "SELECT COUNT(*) FROM targets WHERE target_id NOT IN "
                "(SELECT target_id FROM days) AND target_id NOT IN "
                "(SELECT target_id FROM instant_trials)").fetchone()[0]:
            faults.append("targets: a photograph that was not a target")
        faults.extend(_instant_file_faults(connection))

        for player, named in connection.execute(
                "SELECT player, named FROM players"):
            anonymous = _ANONYMOUS_RULE.fullmatch(player) is not None
            if anonymous == bool(named):
                faults.append(f"players: {player!r} has named {named}")

        if connection.execute(
                "SELECT COUNT(*) FROM submissions WHERE withheld = 1 AND "
                "(record_json IS NOT NULL OR pasted_text IS NOT NULL)"
                ).fetchone()[0]:
            faults.append("a withheld response has its text")
        if connection.execute(
                "SELECT COUNT(*) FROM submissions WHERE withheld = 0 AND "
                "record_json IS NULL").fetchone()[0]:
            faults.append("a response that is not withheld has no record")
        for table in ("impressions", "strokes", "groups", "relations"):
            if connection.execute(
                    f"SELECT COUNT(*) FROM {table} AS c JOIN submissions "
                    "AS s ON s.day = c.day AND s.player = c.player "
                    "WHERE s.withheld = 1").fetchone()[0]:
                faults.append(f"{table}: a row of a withheld response")
        if connection.execute(
                "SELECT COUNT(*) FROM trial_atoms AS a JOIN submissions "
                "AS s ON s.day = a.day AND s.player = a.player "
                "WHERE s.withheld = 1 AND a.atom_text IS NOT NULL"
                ).fetchone()[0]:
            faults.append("trial_atoms: the text of a withheld response")
        for counts, table in (("impression_count", "impressions"),
                              ("stroke_count", "strokes"),
                              ("group_count", "groups"),
                              ("relation_count", "relations")):
            if connection.execute(
                    f"SELECT COUNT(*) FROM submissions AS s WHERE "
                    f"s.withheld = 0 AND s.{counts} != (SELECT COUNT(*) "
                    f"FROM {table} AS c WHERE c.day = s.day AND "
                    "c.player = s.player)").fetchone()[0]:
                faults.append(f"{table}: the rows do not agree with "
                              f"submissions.{counts}")
    finally:
        connection.close()
    return faults


def _instant_file_faults(connection: sqlite3.Connection) -> list[str]:
    """The faults of the instant tables of one built file (spec IM1
    section 13): the pick of each trial, the chain of the sends, the
    owners, and the rule of a withheld response."""
    faults: list[str] = []
    for (trial_id, target_id, label, chain, signature, randomness, nonce,
         commitment, digest, index, salt, proof, count, root) in \
            connection.execute(
                "SELECT trial_id, target_id, pool_label, beacon_chain, "
                "beacon_signature, randomness, nonce, commitment, "
                "send_digest, target_index, target_salt, target_proof, "
                "pool_image_count, pool_root FROM instant_trials"):
        faults.extend(instant_faults(
            trial_id=trial_id, send_digest=digest, commitment=commitment,
            nonce=nonce, signature=signature, randomness=randomness,
            target_id=target_id, target_index=index, target_salt=salt,
            target_proof=json.loads(proof), pool_count=count,
            pool_root=root))
        if label.startswith("dev-"):
            faults.append(f"instant trial {trial_id}: a trial of a "
                          "development pool")
        if chain not in PUBLIC_CHAINS:
            faults.append(f"instant trial {trial_id}: the beacon {chain!r} "
                          "is not a public beacon")
    rows = [instant.ChainRow(*row) for row in connection.execute(
        "SELECT chain_position, chain_previous, chain_link, trial_id, "
        "send_digest, commitment, received_at, beacon_round "
        "FROM instant_chain ORDER BY chain_position")]
    faults.extend(f"instant_chain: {fault}"
                  for fault in instant.chain_faults(rows))
    if connection.execute(
            "SELECT COUNT(*) FROM instant_trials AS t LEFT JOIN "
            "instant_chain AS c ON c.trial_id = t.trial_id WHERE "
            "c.trial_id IS NULL OR c.settled != 1 OR "
            "c.chain_position != t.chain_position OR "
            "c.send_digest != t.send_digest OR "
            "c.commitment != t.commitment OR "
            "c.received_at != t.received_at OR "
            "c.beacon_round != t.beacon_round").fetchone()[0]:
        faults.append("instant_trials: a trial that does not agree with "
                      "its row in instant_chain")
    if connection.execute(
            "SELECT COUNT(*) FROM instant_chain WHERE settled = 1 AND "
            "trial_id NOT IN (SELECT trial_id FROM instant_trials)"
            ).fetchone()[0]:
        faults.append("instant_chain: a settled mark with no trial")
    if connection.execute(
            "SELECT COUNT(*) FROM instant_trials WHERE owner NOT IN "
            "(SELECT owner FROM instant_owners)").fetchone()[0]:
        faults.append("instant_trials: an owner that is not in "
                      "instant_owners")
    for owner, kind, named in connection.execute(
            "SELECT owner, kind, named FROM instant_owners"):
        guest = guests.is_guest_id(owner)
        anonymous = _ANONYMOUS_RULE.fullmatch(owner) is not None
        if guest != (kind == instant.GUEST) \
                or bool(named) != (not guest and not anonymous):
            faults.append(f"instant_owners: {owner!r} has kind {kind!r} "
                          f"and named {named}")
    for table in ("instant_submissions", "instant_impressions",
                  "instant_strokes", "instant_groups", "instant_relations",
                  "instant_trial_atoms", "instant_trial_channels"):
        orphans = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE trial_id NOT IN "
            "(SELECT trial_id FROM instant_trials)").fetchone()[0]
        if orphans:
            faults.append(f"{table}: {orphans} row(s) of a trial that is "
                          "not in instant_trials")
    if connection.execute(
            "SELECT COUNT(*) FROM instant_trials WHERE trial_id NOT IN "
            "(SELECT trial_id FROM instant_submissions)").fetchone()[0]:
        faults.append("instant_trials: a trial with no response row")
    if connection.execute(
            "SELECT COUNT(*) FROM instant_submissions WHERE withheld = 1 "
            "AND (record_json IS NOT NULL OR pasted_text IS NOT NULL)"
            ).fetchone()[0]:
        faults.append("a withheld instant response has its text")
    if connection.execute(
            "SELECT COUNT(*) FROM instant_submissions WHERE withheld = 0 "
            "AND record_json IS NULL").fetchone()[0]:
        faults.append("an instant response that is not withheld has no "
                      "record")
    for counts, table in _INSTANT_RESPONSE_TABLES:
        if connection.execute(
                f"SELECT COUNT(*) FROM {table} AS c JOIN "
                "instant_submissions AS s ON s.trial_id = c.trial_id "
                "WHERE s.withheld = 1").fetchone()[0]:
            faults.append(f"{table}: a row of a withheld response")
        if connection.execute(
                f"SELECT COUNT(*) FROM instant_submissions AS s WHERE "
                f"s.withheld = 0 AND s.{counts} != (SELECT COUNT(*) FROM "
                f"{table} AS c WHERE c.trial_id = s.trial_id)"
                ).fetchone()[0]:
            faults.append(f"{table}: the rows do not agree with "
                          f"instant_submissions.{counts}")
    if connection.execute(
            "SELECT COUNT(*) FROM instant_trial_atoms AS a JOIN "
            "instant_submissions AS s ON s.trial_id = a.trial_id "
            "WHERE s.withheld = 1 AND a.atom_text IS NOT NULL"
            ).fetchone()[0]:
        faults.append("instant_trial_atoms: the text of a withheld "
                      "response")
    return faults


def summary_lines(directory: Path) -> list[str]:
    """What the operator reads before a snapshot goes out: the counts,
    and the days of the withheld responses."""
    target = _snapshot_file(directory)
    connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        meta = dict(connection.execute("SELECT key, value FROM meta"))
        lines = [f"snapshot {target.name}",
                 f"days {meta.get('day_count')} "
                 f"({meta.get('first_day')} to {meta.get('last_day')})"]
        lines += [f"rows {table} {count}"
                  for table, count in _row_counts(connection).items()]
        withheld = [row[0] for row in connection.execute(
            "SELECT day FROM submissions WHERE withheld = 1 ORDER BY day")]
        lines.append(f"withheld {len(withheld)}"
                     + (f" on {', '.join(sorted(set(withheld)))}"
                        if withheld else ""))
        anonymous = connection.execute(
            "SELECT COUNT(*) FROM players WHERE named = 0").fetchone()[0]
        lines.append(f"players with no username {anonymous}")
        lines.append(
            f"instant trials {meta.get('instant_trial_count')} of "
            f"{meta.get('instant_send_count')} sends, withheld "
            f"{meta.get('instant_withheld_count')}")
        guests_shown = connection.execute(
            "SELECT COUNT(*) FROM instant_owners WHERE kind = 'guest'"
            ).fetchone()[0]
        lines.append(f"instant owners that are guests {guests_shown}")
    finally:
        connection.close()
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.public")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build")
    build_parser.add_argument("--out", type=Path, required=True)
    build_parser.add_argument("--date", default=None,
                              help="the snapshot date, YYYY-MM-DD; the "
                                   "default is the UTC date of the build")
    check_parser = commands.add_parser("check")
    check_parser.add_argument("directory", type=Path)
    withhold_parser = commands.add_parser("withhold")
    withhold_parser.add_argument("day")
    withhold_parser.add_argument("player")
    withhold_parser.add_argument("--note", required=True)
    release_parser = commands.add_parser("release")
    release_parser.add_argument("day")
    release_parser.add_argument("player")
    commands.add_parser("withheld")
    # The response of one instant trial (spec IM1 section 10).
    instant_withhold = commands.add_parser("withhold-instant")
    instant_withhold.add_argument("date")
    instant_withhold.add_argument("trial_id")
    instant_withhold.add_argument("--note", required=True)
    instant_release = commands.add_parser("release-instant")
    instant_release.add_argument("date")
    instant_release.add_argument("trial_id")
    commands.add_parser("identifiers")
    arguments = parser.parse_args(argv)
    instant = datetime.datetime.now(datetime.UTC)

    try:
        if arguments.command == "check":
            faults = check(arguments.directory)
            for line in summary_lines(arguments.directory):
                print(line)
            for fault in faults:
                print(f"FAULT: {fault}", file=sys.stderr)
            if faults:
                return 1
            print("check: no fault")
            return 0
        service_config = load_service_config(Path(arguments.service_config))
        root = Path(service_config.store_root)
        if arguments.command == "build":
            target = build(
                root, Path(service_config.data_root), arguments.out,
                snapshot_date=arguments.date or instant.date().isoformat(),
                built_at=instant.isoformat(), version=code_version())
            faults = check(arguments.out)
            for line in summary_lines(arguments.out):
                print(line)
            for fault in faults:
                print(f"FAULT: {fault}", file=sys.stderr)
            if faults:
                return 1
            print(f"built {target} - read it, then publish it by hand")
        elif arguments.command == "withhold":
            if not store.submission_path(root, arguments.day,
                                         arguments.player).is_file():
                raise store.StoreError(
                    f"no submission of {arguments.player!r} on "
                    f"{arguments.day}")
            store.write_withheld(root, store.WithheldRecord(
                day=arguments.day, player=arguments.player,
                withheld_at=instant.isoformat(), note=arguments.note))
            print(f"withheld {arguments.day} {arguments.player} - an "
                  "earlier snapshot does not change")
        elif arguments.command == "release":
            removed = store.remove_withheld(root, arguments.day,
                                            arguments.player)
            print(f"released {arguments.day} {arguments.player}" if removed
                  else f"{arguments.day} {arguments.player} was not withheld")
        elif arguments.command == "withheld":
            for record in store.list_withheld(root):
                print(f"{record.day}  {record.player}  {record.withheld_at}  "
                      f"{record.note}")
            for trial in instant_store.list_withheld(root):
                print(f"instant {trial.date}  {trial.trial_id}  "
                      f"{trial.withheld_at}  {trial.note}")
        elif arguments.command == "withhold-instant":
            if instant_store.read_send_or_none(
                    root, arguments.date, arguments.trial_id) is None:
                raise store.StoreError(
                    f"no send of the instant trial {arguments.date} "
                    f"{arguments.trial_id}")
            instant_store.write_withheld(root, instant_store.WithheldTrial(
                date=arguments.date, trial_id=arguments.trial_id,
                withheld_at=instant.isoformat(), note=arguments.note))
            print(f"withheld the instant trial {arguments.date} "
                  f"{arguments.trial_id} - its page shows no sketch")
        elif arguments.command == "release-instant":
            removed = instant_store.remove_withheld(
                root, arguments.date, arguments.trial_id)
            print(f"released the instant trial {arguments.date} "
                  f"{arguments.trial_id}" if removed
                  else f"the instant trial {arguments.date} "
                  f"{arguments.trial_id} was not withheld")
        elif arguments.command == "identifiers":
            written = write_identifiers(root, instant)
            print(f"wrote {len(written)} identifier record(s)")
    except (ServiceConfigError, store.StoreError, PublicBuildError,
            ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
