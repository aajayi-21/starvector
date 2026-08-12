"""The permanent trial store: days, submissions, trial rows.

Spec: S1 (in docs/specs/) section 5. The store is not a cache -
nothing in it is rebuildable from elsewhere (Rule 4). Submissions
and trial rows are one-write files: the writer makes them with an
atomic, refusing primitive, and no code path edits them. The day
record has one sanctioned edit path, the guarded status move.
"""

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

from core.canonical import JsonValue, canonical_json_pretty
from pool.artifacts import write_json_pretty

DAY_STATUSES = ("open", "closed", "revealed")

_DAY_RULE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_DAY_FIELDS = ("day", "trial_code", "target_id", "pick_seed", "secret",
               "commitment",
               "scoring_config_path", "scoring_config_hash",
               "preparation_version_id", "status", "opened_at", "closed_at",
               "revealed_at")

_README = """\
# The trial store

This directory is the permanent record of play: day records, raw
player submissions, and trial rows (spec S1 in docs/specs/,
section 5). It is not a cache - nothing here is rebuildable from
elsewhere, and Rule 4 of CLAUDE.md applies: raw submissions are
stored forever. Keep it in every backup. The directory sits in
.gitignore because play records are data, not code.
"""


class StoreError(ValueError):
    """A store rule was broken or a stored document did not parse."""


@dataclass(frozen=True, slots=True)
class DayRecord:
    """The stored facts of one day (spec S1 sections 3 and 5).

    trial_code is the player-facing identifier of the hidden target:
    six random characters, A-Z and 0-9, with no derivation from the
    image (the section 22 hygiene rule and the section 14b ruling
    of 2026-08-12). The page shows it front and center.
    """

    day: str
    trial_code: str
    target_id: str
    pick_seed: str
    secret: str
    commitment: str
    scoring_config_path: str
    scoring_config_hash: str
    preparation_version_id: str
    status: str
    opened_at: str
    closed_at: str | None
    revealed_at: str | None


def ensure_store(store: Path) -> None:
    """Make the store root and its permanence README, one time."""
    store.mkdir(parents=True, exist_ok=True)
    readme = store / "README.md"
    if not readme.is_file():
        readme.write_text(_README, encoding="utf-8")


def day_dir(store: Path, day: str) -> Path:
    return store / "days" / day


def day_record_path(store: Path, day: str) -> Path:
    return day_dir(store, day) / "day.json"


def submission_path(store: Path, day: str, player: str) -> Path:
    return day_dir(store, day) / "submissions" / f"{player}.json"


def trial_row_path(store: Path, day: str, player: str,
                   scoring_hash8: str | None = None) -> Path:
    """The trial-row file, or the adjacent rescore file (S1 R8)."""
    name = f"{player}.json" if scoring_hash8 is None \
        else f"{player}.{scoring_hash8}.json"
    return day_dir(store, day) / "trials" / name


def list_days(store: Path) -> tuple[str, ...]:
    """The stored day identifiers, ascending."""
    root = store / "days"
    if not root.is_dir():
        return ()
    return tuple(sorted(
        entry.name for entry in root.iterdir()
        if entry.is_dir() and _DAY_RULE.match(entry.name)))


def latest_day(store: Path) -> str | None:
    """The most recent stored day, or None (S1 section 14a, OP7)."""
    days = list_days(store)
    return days[-1] if days else None


def write_once_json(path: Path, value: JsonValue) -> None:
    """Write one JSON document atomically, refusing a second write.

    The document lands in a temporary sibling, and an atomic claim
    then takes the destination - a primitive that refuses an
    existing file - thus two racing writers get one file and one
    StoreError, with no half-written file in each outcome.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (path.name + ".tmp")
    temporary.write_text(canonical_json_pretty(value) + "\n",
                         encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise StoreError(
            f"{path}: the store is one-write and the file exists") from error
    finally:
        temporary.unlink(missing_ok=True)


def _day_to_value(record: DayRecord) -> dict[str, JsonValue]:
    return {
        "day": record.day,
        "trial_code": record.trial_code,
        "target_id": record.target_id,
        "pick_seed": record.pick_seed,
        "secret": record.secret,
        "commitment": record.commitment,
        "scoring_config_path": record.scoring_config_path,
        "scoring_config_hash": record.scoring_config_hash,
        "preparation_version_id": record.preparation_version_id,
        "status": record.status,
        "opened_at": record.opened_at,
        "closed_at": record.closed_at,
        "revealed_at": record.revealed_at,
    }


def write_day_record(store: Path, record: DayRecord) -> None:
    """Write a new day record - open alone does this, one time."""
    if record.status != "open":
        raise StoreError(
            f"a new day record must have status 'open', got {record.status!r}")
    write_once_json(day_record_path(store, record.day),
                    _day_to_value(record))


def read_day_record(store: Path, day: str) -> DayRecord:
    """Read and validate one stored day record, strict."""
    import json

    path = day_record_path(store, day)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"{path}: cannot read the day record: {error}") \
            from error
    if not isinstance(raw, dict) or set(raw) != set(_DAY_FIELDS):
        raise StoreError(
            f"{path}: the day record must have the fields "
            f"{sorted(_DAY_FIELDS)}")
    for name in _DAY_FIELDS:
        value = raw[name]
        if name in ("closed_at", "revealed_at"):
            if value is not None and not isinstance(value, str):
                raise StoreError(f"{path}.{name}: expected a string or null")
            continue
        if not isinstance(value, str) or not value:
            raise StoreError(f"{path}.{name}: expected a non-empty string")
    if raw["status"] not in DAY_STATUSES:
        raise StoreError(
            f"{path}.status: expected one of {list(DAY_STATUSES)}")
    if not re.match(r"^[A-Z0-9]{6}$", raw["trial_code"]):
        raise StoreError(
            f"{path}.trial_code: expected six characters, A-Z and 0-9")
    return DayRecord(**raw)


def update_day_status(store: Path, day: str, *, expect_status: str,
                      new_status: str, timestamp_field: str,
                      timestamp: str) -> DayRecord:
    """The one sanctioned day-record edit: the guarded status move.

    Reads the stored record again, refuses unless its status equals
    expect_status (the out-of-sequence guard), then writes the moved
    record atomically. Submissions and trial rows have no edit path
    at all (R2).
    """
    if new_status not in DAY_STATUSES:
        raise StoreError(f"unknown status: {new_status!r}")
    if timestamp_field not in ("closed_at", "revealed_at"):
        raise StoreError(f"unknown timestamp field: {timestamp_field!r}")
    record = read_day_record(store, day)
    if record.status != expect_status:
        raise StoreError(
            f"day {day} has status {record.status!r} and the move needs "
            f"{expect_status!r}")
    moved = replace(record, status=new_status,
                    **{timestamp_field: timestamp})
    write_json_pretty(day_record_path(store, day), _day_to_value(moved))
    return moved


def read_json_or_none(path: Path) -> dict | None:
    """One stored JSON object, or None when the file is not there."""
    import json

    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"{path}: cannot read: {error}") from error
    if not isinstance(raw, dict):
        raise StoreError(f"{path}: expected a JSON object")
    return raw


def list_submissions(store: Path, day: str) -> tuple[str, ...]:
    """The player names with a stored submission, ascending."""
    root = day_dir(store, day) / "submissions"
    if not root.is_dir():
        return ()
    return tuple(sorted(
        entry.name[:-5] for entry in root.iterdir()
        if entry.is_file() and entry.name.endswith(".json")
        and not entry.name.endswith(".tmp")))
