"""The results index: a SQLite copy of the store, for programs to read.

Spec: BR1 (in docs/specs/beta-readiness.md) section 5. The store
files stay the source of truth (CLAUDE.md I4). This database is a
cache that a command makes again from the store at each moment: a
build reads each record and writes a new file, and os.replace puts
it in position, thus a reader does not see a half-built index. No code
writes the index row by row, thus the index and the store cannot
drift apart through a missed write.

The fences:

- I7: trial rows come in for revealed days alone, and a day's target
  and secret stay NULL until its reveal. An index copied off the box
  for analysis thus holds no score of a day that is not public.
- I6: nothing on the fit side imports this module. A test scans each
  fit-side package for the import.
- token_hash, sessions, and device codes stay out: they are
  credentials, not results.

The command line of this module has four commands: build makes the
index again from the store, a compare against the store checks it,
export writes the research set of revealed days, and path prints
where the index is. The operator console (spec BR1 section 7.3)
reads the index through describe and read_only_query.
"""

import argparse
import csv
import datetime
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from service import store
from service.config import ServiceConfigError, load_service_config

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE players (
  player TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE accounts (
  player TEXT PRIMARY KEY,
  description TEXT NOT NULL,
  avatar_hash TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE days (
  day TEXT PRIMARY KEY,
  trial_code TEXT NOT NULL,
  status TEXT NOT NULL,
  commitment TEXT NOT NULL,
  target_id TEXT,
  secret TEXT,
  scoring_config_path TEXT NOT NULL,
  scoring_config_hash TEXT NOT NULL,
  preparation_version_id TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  revealed_at TEXT
);
CREATE TABLE submissions (
  day TEXT NOT NULL REFERENCES days (day),
  player TEXT NOT NULL,
  trial_id TEXT NOT NULL,
  received_at TEXT NOT NULL,
  impression_count INTEGER NOT NULL,
  stroke_count INTEGER NOT NULL,
  group_count INTEGER NOT NULL,
  relation_count INTEGER NOT NULL,
  has_pasted_text INTEGER NOT NULL,
  record_json TEXT NOT NULL,
  PRIMARY KEY (day, player)
);
CREATE TABLE trials (
  day TEXT NOT NULL REFERENCES days (day),
  player TEXT NOT NULL,
  scoring_config_hash TEXT NOT NULL,
  pinned INTEGER NOT NULL,
  trial_id TEXT NOT NULL,
  p REAL NOT NULL,
  target_rank INTEGER NOT NULL,
  decoy_count INTEGER NOT NULL,
  beaten INTEGER NOT NULL,
  tied INTEGER NOT NULL,
  commonness_config_hash TEXT,
  preparation_version_id TEXT NOT NULL,
  PRIMARY KEY (day, player, scoring_config_hash)
);
CREATE TABLE trial_atoms (
  day TEXT NOT NULL,
  player TEXT NOT NULL,
  scoring_config_hash TEXT NOT NULL,
  position INTEGER NOT NULL,
  atom_id TEXT NOT NULL,
  atom_text TEXT,
  element TEXT,
  weight REAL,
  similarity REAL,
  rarity REAL,
  PRIMARY KEY (day, player, scoring_config_hash, position)
);
CREATE VIEW revealed_trials AS
  SELECT t.*, d.trial_code, d.target_id, s.received_at
  FROM trials AS t
  JOIN days AS d ON d.day = t.day
  LEFT JOIN submissions AS s ON s.day = t.day AND s.player = t.player
  WHERE d.status = 'revealed' AND t.pinned = 1;
CREATE INDEX trials_by_player ON trials (player, day);
"""

# The tables in a fixed sequence, with the key columns each compare
# sorts on.
_TABLES = (
    ("players", "player"),
    ("accounts", "player"),
    ("days", "day"),
    ("submissions", "day, player"),
    ("trials", "day, player, scoring_config_hash"),
    ("trial_atoms", "day, player, scoring_config_hash, position"),
)


# The limits of the console's read-only query (spec BR1 section 7.3).
QUERY_ROW_CAP = 1000
QUERY_SECONDS = 5.0
QUERY_TEXT_CAP = 10_000
QUERY_VALUE_BYTES = 10_000_000


class ResultsIndexError(RuntimeError):
    """The index cannot be built, read, or exported as asked."""


def index_path(data_root: Path) -> Path:
    """Where the index lives: below the data root, a cache like it."""
    return Path(data_root) / "index" / f"results-v{SCHEMA_VERSION}.sqlite"


def _record_files(root: Path) -> Iterator[Path]:
    """Each store file the index reads, in a fixed sequence."""
    for day in store.list_days(root):
        directory = store.day_dir(root, day)
        yield directory / "day.json"
        for folder in ("submissions", "trials"):
            base = directory / folder
            if base.is_dir():
                yield from sorted(path for path in base.iterdir()
                                  if path.is_file()
                                  and path.name.endswith(".json"))
    for folder in ("players", "accounts"):
        base = root / folder
        if base.is_dir():
            yield from sorted(path for path in base.iterdir()
                              if path.is_file()
                              and path.name.endswith(".json"))


def store_fingerprint(root: Path) -> str:
    """A digest of the name, length, and change time of each record file.

    A write to the store changes one of the three for the file it
    writes, thus an index built at one fingerprint is current while
    the fingerprint stays equal. It reads directory entries and
    file metadata, not contents - cheap at beta scale.
    """
    digest = hashlib.sha256()
    for path in _record_files(root):
        facts = path.stat()
        relative = path.relative_to(root).as_posix()
        digest.update(f"{relative}\0{facts.st_size}\0"
                      f"{facts.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def _counts(record: dict) -> tuple[int, int, int, int, int]:
    impressions = record.get("impressions") or []
    strokes = record.get("canvas_strokes") or []
    groups = record.get("groups") or []
    relations = record.get("relations") or []
    pasted = record.get("pasted_text")
    return (len(impressions), len(strokes), len(groups), len(relations),
            1 if isinstance(pasted, str) and pasted.strip() else 0)


def _trial_files(root: Path, day: str) -> Iterator[tuple[str, bool, dict]]:
    """Each trial row of one day as (player, pinned, row)."""
    base = store.day_dir(root, day) / "trials"
    if not base.is_dir():
        return
    for path in sorted(base.iterdir()):
        name = path.name
        if not (path.is_file() and name.endswith(".json")):
            continue
        stem = name[:-5]
        player, _dot, _hash8 = stem.partition(".")
        row = store.read_json_or_none(path)
        if row is None:
            continue
        if row.get("player") != player:
            raise ResultsIndexError(
                f"{path}: the row names {row.get('player')!r}")
        yield player, _dot == "", row


def _fill(connection: sqlite3.Connection, root: Path) -> None:
    """Write each store record into an empty schema."""
    for name in store.list_players(root):
        record = store.read_player_record(root, name)
        connection.execute(
            "INSERT INTO players VALUES (?, ?, ?, ?)",
            (record.player, record.display_name, record.status,
             record.created_at))
        account = store.read_account_or_none(root, name)
        if account is not None:
            connection.execute(
                "INSERT INTO accounts VALUES (?, ?, ?, ?)",
                (account.player, account.description, account.avatar_hash,
                 account.updated_at))
    for day in store.list_days(root):
        record = store.read_day_record(root, day)
        revealed = record.status == "revealed"
        connection.execute(
            "INSERT INTO days VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record.day, record.trial_code, record.status, record.commitment,
             record.target_id if revealed else None,
             record.secret if revealed else None,
             record.scoring_config_path, record.scoring_config_hash,
             record.preparation_version_id, record.opened_at,
             record.closed_at, record.revealed_at))
        for player in store.list_submissions(root, day):
            stored = store.read_json_or_none(
                store.submission_path(root, day, player))
            if stored is None or not isinstance(stored.get("record"), dict):
                raise ResultsIndexError(
                    f"day {day}: the submission of {player} does not parse")
            wire = stored["record"]
            connection.execute(
                "INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (day, player, str(stored["trial_id"]),
                 str(stored["received_at"]), *_counts(wire),
                 json.dumps(wire, sort_keys=True, separators=(",", ":"))))
        if not revealed:
            continue
        for player, pinned, row in _trial_files(root, day):
            config_hash = str(row["scoring_config_hash"])
            connection.execute(
                "INSERT INTO trials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (day, player, config_hash, 1 if pinned else 0,
                 str(row["trial_id"]), float(row["p"]),
                 int(row["target_rank"]), int(row["decoy_count"]),
                 int(row["beaten"]), int(row["tied"]),
                 row.get("commonness_config_hash"),
                 str(row["preparation_version_id"])))
            for position, atom in enumerate(row.get("report") or []):
                connection.execute(
                    "INSERT INTO trial_atoms VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (day, player, config_hash, position,
                     str(atom.get("atom_id")), atom.get("atom_text"),
                     atom.get("element"), atom.get("weight"),
                     atom.get("similarity"), atom.get("rarity")))


def _write(path: Path, root: Path, fingerprint: str,
           built_at: str) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_SCHEMA)
        _fill(connection, root)
        connection.executemany(
            "INSERT INTO meta VALUES (?, ?)",
            (("schema_version", str(SCHEMA_VERSION)),
             ("store_fingerprint", fingerprint),
             ("built_at", built_at)))
        connection.commit()
    finally:
        connection.close()


def build(root: Path, target: Path, *,
          built_at: str | None = None) -> str:
    """Make the index again from the store, and answer the fingerprint.

    The build writes a temporary sibling and os.replace moves it into
    position, thus a reader holds the earlier file or the new one and
    not half of each. The fingerprint is read before the records:
    a store write during the build then leaves the index one
    fingerprint behind, and the next check builds again.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = store_fingerprint(root)
    stamp = built_at or datetime.datetime.now(datetime.UTC).isoformat()
    handle, name = tempfile.mkstemp(dir=target.parent,
                                    prefix=target.name + ".",
                                    suffix=".tmp")
    os.close(handle)
    temporary = Path(name)
    temporary.unlink()
    try:
        _write(temporary, root, fingerprint, stamp)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return fingerprint


def read_fingerprint(target: Path) -> str | None:
    """The fingerprint an index file was built at, or None."""
    if not target.is_file():
        return None
    connection = connect(target)
    try:
        found = connection.execute(
            "SELECT value FROM meta WHERE key = 'store_fingerprint'"
        ).fetchone()
    except sqlite3.DatabaseError:
        return None
    finally:
        connection.close()
    return None if found is None else str(found[0])


_build_lock = threading.Lock()


def ensure_current(root: Path, target: Path) -> Path:
    """The index path, after a build when the store moved since the last.

    One build at a time in this process. Two processes that build at
    one moment each write a complete file, and the last replace wins -
    the two files hold the same rows.
    """
    with _build_lock:
        if read_fingerprint(target) != store_fingerprint(root):
            build(root, target)
    return target


def connect(target: Path) -> sqlite3.Connection:
    """A read-only connection to the index file."""
    connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _rows(connection: sqlite3.Connection, table: str,
          order: str) -> list[tuple]:
    return [tuple(row) for row in
            connection.execute(f"SELECT * FROM {table} ORDER BY {order}")]


def verify(root: Path, target: Path) -> list[str]:
    """Compare the index with a new build from the store, table by table.

    Answers one line for each table that differs, and no line when
    the two agree. The new build goes to a temporary file and is
    removed after.
    """
    if not target.is_file():
        return [f"{target}: no index file"]
    with tempfile.TemporaryDirectory() as scratch:
        fresh = Path(scratch) / "fresh.sqlite"
        build(root, fresh)
        stored = connect(target)
        rebuilt = connect(fresh)
        try:
            problems = []
            for table, order in _TABLES:
                left = _rows(stored, table, order)
                right = _rows(rebuilt, table, order)
                if left != right:
                    missing = len(set(right) - set(left))
                    extra = len(set(left) - set(right))
                    problems.append(
                        f"{table}: {missing} rows missing from the index, "
                        f"{extra} rows the store does not hold")
            return problems
        finally:
            stored.close()
            rebuilt.close()


def describe(root: Path, target: Path) -> dict:
    """The index file for the console: the build time, if it agrees
    with the store, and each table and view with its columns and row
    count. A read alone - no build.

    A file that SQLite cannot read gives its error as problem, thus the
    console offers a build and does not stop.
    """
    value: dict = {"path": str(target), "exists": target.is_file(),
                   "schema_version": SCHEMA_VERSION, "built_at": None,
                   "current": False, "problem": None, "tables": []}
    if not value["exists"]:
        return value
    connection = connect(target)
    try:
        meta = {str(row[0]): str(row[1]) for row in
                connection.execute("SELECT key, value FROM meta")}
        tables = []
        for name in [table for table, _order in _TABLES] \
                + ["revealed_trials"]:
            rows = connection.execute(
                f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            columns = [str(row[1]) for row in
                       connection.execute(f"PRAGMA table_info({name})")]
            tables.append({"name": name, "rows": int(rows),
                           "columns": columns,
                           "view": name == "revealed_trials"})
    except sqlite3.DatabaseError as error:
        value["problem"] = str(error)
        return value
    finally:
        connection.close()
    value["built_at"] = meta.get("built_at")
    value["current"] = meta.get("store_fingerprint") \
        == store_fingerprint(root)
    value["tables"] = tables
    return value


# The authorizer actions a read-only query needs. Each other action -
# a write, a schema change, ATTACH, PRAGMA, a transaction - refuses.
_READ_ACTIONS = frozenset({sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                           sqlite3.SQLITE_FUNCTION,
                           sqlite3.SQLITE_RECURSIVE})


def _read_only(action: int, _first: str | None, second: str | None,
               _database: str | None, _trigger: str | None) -> int:
    """The authorizer of the console's query: reads alone."""
    if action == sqlite3.SQLITE_FUNCTION and second is not None \
            and second.lower() == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK if action in _READ_ACTIONS \
        else sqlite3.SQLITE_DENY


def _cell(value: object) -> object:
    """One result value in a shape that JSON holds."""
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _query_error(error: Exception) -> str:
    """SQLite's refusal in words that name the cause. The refusal of
    the authorizer names no cause."""
    text = str(error)
    if "not authorized" in text:
        return ("read-only: the query box takes one SELECT - a write, "
                "ATTACH, PRAGMA, and load_extension refuse")
    return text


def read_only_query(target: Path, sql: str, *,
                    row_cap: int = QUERY_ROW_CAP,
                    seconds: float = QUERY_SECONDS) -> dict:
    """Run one SQL statement on the index with no write possible.

    Three layers hold the read-only rule: the file opens in mode=ro,
    PRAGMA query_only is on, and the authorizer refuses each action
    that is not a read. A handler that SQLite starts at intervals stops
    the statement after the time limit, and a length limit stops a
    value that is too large. Answers the columns, row_cap rows at most, a flag when more
    rows agree with the query, and the time taken.

    Raises ResultsIndexError for text that is empty or too long, and
    for a statement that SQLite refuses or stops.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise ResultsIndexError("the query is empty")
    if len(sql) > QUERY_TEXT_CAP:
        raise ResultsIndexError(
            f"the query is longer than {QUERY_TEXT_CAP} characters")
    connection = connect(target)
    started = time.monotonic()
    deadline = started + seconds
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, QUERY_VALUE_BYTES)
        connection.set_authorizer(_read_only)
        connection.set_progress_handler(
            lambda: 1 if time.monotonic() > deadline else 0, 1000)
        cursor = connection.execute(sql)
        if cursor.description is None:
            raise ResultsIndexError("the statement gives no rows - "
                                    "write a SELECT")
        columns = [str(column[0]) for column in cursor.description]
        fetched = cursor.fetchmany(row_cap + 1)
    except sqlite3.OperationalError as error:
        if time.monotonic() > deadline:
            raise ResultsIndexError(
                f"the query ran for more than {seconds:g} seconds and "
                "stopped") from error
        raise ResultsIndexError(_query_error(error)) from error
    except (sqlite3.DatabaseError, sqlite3.ProgrammingError,
            sqlite3.Warning) as error:
        raise ResultsIndexError(_query_error(error)) from error
    finally:
        connection.close()
    return {"columns": columns,
            "rows": [[_cell(value) for value in row]
                     for row in fetched[:row_cap]],
            "truncated": len(fetched) > row_cap,
            "elapsed_ms": round((time.monotonic() - started) * 1000)}


def revealed_trial_rows(target: Path, *, from_day: str | None = None,
                        to_day: str | None = None,
                        player: str | None = None,
                        limit: int = 5000) -> list[dict]:
    """The pinned trial rows of revealed days, with each player's label.

    The operator API reads this. Days before or after the range and
    players other than the named one do not come in. The view does the revealed
    filter, thus no caller can forget it.
    """
    clauses, values = [], []
    if from_day is not None:
        clauses.append("t.day >= ?")
        values.append(from_day)
    if to_day is not None:
        clauses.append("t.day <= ?")
        values.append(to_day)
    if player is not None:
        clauses.append("t.player = ?")
        values.append(player)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    connection = connect(target)
    try:
        rows = connection.execute(
            "SELECT t.day, t.trial_code, t.player, "
            "COALESCE(p.display_name, t.player) AS display_name, t.p, "
            "t.target_rank, t.decoy_count, t.beaten, t.tied, "
            "t.scoring_config_hash, t.preparation_version_id, "
            "t.received_at, t.target_id "
            "FROM revealed_trials AS t "
            "LEFT JOIN players AS p ON p.player = t.player "
            f"{where} ORDER BY t.day, t.player LIMIT ?",
            (*values, limit)).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def pseudonym(player: str, salt: str) -> str:
    """The research name of a player: a salted digest prefix."""
    return hashlib.sha256(f"{salt}\0{player}".encode("utf-8")).hexdigest()[:16]


_EXPORT_TRIALS = (
    "SELECT t.day, t.trial_code, t.target_id, t.player, t.p, t.target_rank, "
    "t.decoy_count, t.beaten, t.tied, t.scoring_config_hash, "
    "t.preparation_version_id FROM revealed_trials AS t "
    "ORDER BY t.day, t.player")
_EXPORT_ATOMS = (
    "SELECT a.day, a.player, a.position, a.atom_text, a.element, a.weight, "
    "a.similarity, a.rarity FROM trial_atoms AS a "
    "JOIN revealed_trials AS t ON t.day = a.day AND t.player = a.player "
    "AND t.scoring_config_hash = a.scoring_config_hash "
    "ORDER BY a.day, a.player, a.position")
_EXPORT_SUBMISSIONS = (
    "SELECT s.day, s.player, s.impression_count, s.stroke_count, "
    "s.group_count, s.relation_count, s.has_pasted_text, s.record_json "
    "FROM submissions AS s JOIN days AS d ON d.day = s.day "
    "WHERE d.status = 'revealed' ORDER BY s.day, s.player")


def export(target: Path, out_dir: Path, *, salt: str,
           file_format: str) -> dict[str, int]:
    """Write the research set: revealed days alone, players by pseudonym.

    Three files: trials, the atom report of each trial, and the raw
    submissions of revealed days. No display name, no description,
    and no store key go in them. Answers the row count of each.
    """
    if not salt:
        raise ResultsIndexError("the export needs a salt - the player names are "
                          "replaced by salted digests")
    if file_format not in ("csv", "jsonl"):
        raise ResultsIndexError(f"unknown format {file_format!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    connection = connect(target)
    try:
        for name, query in (("trials", _EXPORT_TRIALS),
                            ("trial_atoms", _EXPORT_ATOMS),
                            ("submissions", _EXPORT_SUBMISSIONS)):
            cursor = connection.execute(query)
            columns = [column[0] for column in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor]
            for row in rows:
                row["player"] = pseudonym(row["player"], salt)
            counts[name] = len(rows)
            _write_rows(out_dir / f"{name}.{file_format}", columns, rows,
                        file_format)
    finally:
        connection.close()
    return counts


def _write_rows(path: Path, columns: list[str], rows: list[dict],
                file_format: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        if file_format == "csv":
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        else:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="service.index")
    parser.add_argument("--service-config",
                        default="configs/service/dev-wit.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build")
    commands.add_parser("verify")
    commands.add_parser("path")
    export_parser = commands.add_parser("export")
    export_parser.add_argument("--out", required=True)
    export_parser.add_argument("--format", choices=("csv", "jsonl"),
                               default="csv")
    export_parser.add_argument(
        "--salt", default=None,
        help="the pseudonym salt; the default reads STARVECTOR_EXPORT_SALT")
    arguments = parser.parse_args(argv)
    try:
        config = load_service_config(Path(arguments.service_config))
        root = Path(config.store_root)
        target = index_path(Path(config.data_root))
        if arguments.command == "path":
            print(target)
        elif arguments.command == "build":
            fingerprint = build(root, target)
            print(f"index built at {target}  store {fingerprint[:12]}")
        elif arguments.command == "verify":
            problems = verify(root, target)
            for line in problems:
                print(line)
            if problems:
                return 1
            print(f"index agrees with the store: {target}")
        elif arguments.command == "export":
            salt = arguments.salt or os.environ.get("STARVECTOR_EXPORT_SALT")
            ensure_current(root, target)
            counts = export(target, Path(arguments.out), salt=salt or "",
                            file_format=arguments.format)
            print("exported " + "  ".join(
                f"{name}={count}" for name, count in counts.items()))
    except (ServiceConfigError, store.StoreError, ResultsIndexError,
            sqlite3.DatabaseError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
