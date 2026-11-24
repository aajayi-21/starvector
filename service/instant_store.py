"""The stored records of an instant trial (spec IM1 section 12).

Four files for each trial, in store/instant/<date>/<trial_id>/: the
start, the send, the secret, and the result. Each one is a raw fact
(rule I4), and the writer makes each one with the one-write primitive
of store.py. No code path edits them. The date is the UTC date of the
start.
"""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from core.canonical import JsonValue
from service import instant
from service.pick_rule import instant_commitment
from service.store import StoreError, read_json_or_none, write_once_json

_DATE_RULE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TRIAL_RULE = re.compile(r"[0-9a-f]{32}")
_OWNER_RULE = re.compile(r"[a-z0-9-]{1,64}")
_DIGEST_RULE = re.compile(r"[0-9a-f]{64}")
_HEX_RULE = re.compile(r"(?:[0-9a-f]{2})+")

_START_FILE = "start.json"
_SEND_FILE = "send.json"
_SECRET_FILE = "secret.json"
_RESULT_FILE = "result.json"


@dataclass(frozen=True, slots=True)
class StartRecord:
    """The start of one trial: the owner and the code that it sees."""

    trial_id: str
    owner_kind: str
    owner: str
    trial_code: str
    started_at: str


@dataclass(frozen=True, slots=True)
class SendRecord:
    """The one send of a trial, with its pulse and its chain fields.

    record is the wire record as the player sent it. chain_link is the
    chain value of this send, and chain_previous is the chain value of
    the send before it.
    """

    trial_id: str
    owner_kind: str
    owner: str
    received_at: str
    record: JsonValue
    send_digest: str
    commitment: str
    beacon_chain: str
    beacon_round: int
    preparation_version_id: str
    pool_root: str
    pool_count: int
    scoring_config_path: str
    scoring_config_hash: str
    notice: int
    chain_position: int
    chain_previous: str
    chain_link: str


@dataclass(frozen=True, slots=True)
class ResultRecord:
    """The pick and the trial row of one trial.

    row is the trial row of spec S1 for the pinned scoring
    configuration, as a JSON object.
    """

    trial_id: str
    beacon_signature: str
    randomness: str
    nonce: str
    target_index: int
    target_id: str
    target_salt: str
    target_proof: tuple[str, ...]
    settled_at: str
    row: JsonValue


def instant_dir(store: Path) -> Path:
    return store / "instant"


def check_date(value: object, where: str) -> None:
    if not isinstance(value, str) or not _DATE_RULE.fullmatch(value):
        raise StoreError(f"{where}: expected a date YYYY-MM-DD, "
                         f"got {value!r}")


def check_trial_id(value: object, where: str) -> None:
    if not isinstance(value, str) or not _TRIAL_RULE.fullmatch(value):
        raise StoreError(f"{where}: expected 32 lowercase hex characters, "
                         f"got {value!r}")


def trial_dir(store: Path, date: str, trial_id: str) -> Path:
    """The directory of one trial. The two names become file names,
    thus each one must agree with its rule in full."""
    check_date(date, "date")
    check_trial_id(trial_id, "trial_id")
    return instant_dir(store) / date / trial_id


def _text(value: object, where: str) -> None:
    if not isinstance(value, str) or not value:
        raise StoreError(f"{where}: expected a non-empty string")


def _stamp(value: object, where: str) -> None:
    _text(value, where)
    try:
        instant.unix_seconds(str(value))
    except instant.InstantError as error:
        raise StoreError(f"{where}: {error}") from error


def _count(value: object, where: str, low: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < low:
        raise StoreError(f"{where}: expected an integer of {low} or more, "
                         f"got {value!r}")


def _digest(value: object, where: str) -> None:
    if not isinstance(value, str) or not _DIGEST_RULE.fullmatch(value):
        raise StoreError(f"{where}: expected 64 lowercase hex characters")


def _owner(kind: object, key: object, where: str) -> None:
    if kind not in instant.OWNER_KINDS:
        raise StoreError(f"{where}.owner_kind: expected one of "
                         f"{instant.OWNER_KINDS}, got {kind!r}")
    if not isinstance(key, str) or not _OWNER_RULE.fullmatch(key):
        raise StoreError(f"{where}.owner: not an owner name: {key!r}")


def _check_start(record: StartRecord, where: str) -> None:
    check_trial_id(record.trial_id, f"{where}.trial_id")
    _owner(record.owner_kind, record.owner, where)
    _text(record.trial_code, f"{where}.trial_code")
    _stamp(record.started_at, f"{where}.started_at")


def _check_send(record: SendRecord, where: str) -> None:
    check_trial_id(record.trial_id, f"{where}.trial_id")
    _owner(record.owner_kind, record.owner, where)
    _stamp(record.received_at, f"{where}.received_at")
    if not isinstance(record.record, dict):
        raise StoreError(f"{where}.record: expected a JSON object")
    _digest(record.send_digest, f"{where}.send_digest")
    if instant.send_digest(record.record) != record.send_digest:
        raise StoreError(f"{where}: send_digest is not the digest of "
                         "the record")
    _digest(record.commitment, f"{where}.commitment")
    _text(record.beacon_chain, f"{where}.beacon_chain")
    _count(record.beacon_round, f"{where}.beacon_round", 1)
    _text(record.preparation_version_id,
          f"{where}.preparation_version_id")
    _digest(record.pool_root, f"{where}.pool_root")
    _count(record.pool_count, f"{where}.pool_count", 1)
    _text(record.scoring_config_path, f"{where}.scoring_config_path")
    _digest(record.scoring_config_hash, f"{where}.scoring_config_hash")
    _count(record.notice, f"{where}.notice", 1)
    _count(record.chain_position, f"{where}.chain_position", 0)
    _digest(record.chain_previous, f"{where}.chain_previous")
    _digest(record.chain_link, f"{where}.chain_link")
    expected = instant.chain_digest(
        record.chain_previous, trial_id=record.trial_id,
        send_digest=record.send_digest, commitment=record.commitment,
        received_at=record.received_at, beacon_round=record.beacon_round)
    if expected != record.chain_link:
        raise StoreError(f"{where}: chain_link is not the chain value of "
                         "the send")


def _check_result(record: ResultRecord, where: str) -> None:
    check_trial_id(record.trial_id, f"{where}.trial_id")
    for name in ("beacon_signature", "randomness", "nonce", "target_salt"):
        value = getattr(record, name)
        if not isinstance(value, str) or not _HEX_RULE.fullmatch(value):
            raise StoreError(f"{where}.{name}: expected lowercase hex")
    _digest(record.randomness, f"{where}.randomness")
    _digest(record.nonce, f"{where}.nonce")
    _count(record.target_index, f"{where}.target_index", 0)
    _text(record.target_id, f"{where}.target_id")
    if not isinstance(record.target_proof, tuple) or not all(
            isinstance(step, str) for step in record.target_proof):
        raise StoreError(f"{where}.target_proof: expected proof steps")
    _stamp(record.settled_at, f"{where}.settled_at")
    if not isinstance(record.row, dict) \
            or record.row.get("trial_id") != record.trial_id:
        raise StoreError(f"{where}.row: expected the trial row of "
                         f"{record.trial_id}")


def _names(record_type: type) -> tuple[str, ...]:
    return tuple(field.name for field in fields(record_type))


def _raw(path: Path, record_type: type, trial_id: str) -> dict | None:
    """The stored object of one file, with the field names checked.

    A file with a different set of names, or with the name of a
    different trial, raises: it does not read as a record.
    """
    raw = read_json_or_none(path)
    if raw is None:
        return None
    if set(raw) != set(_names(record_type)) \
            or raw.get("trial_id") != trial_id:
        raise StoreError(f"{path}: not the {record_type.__name__} of "
                         f"trial {trial_id}")
    return raw


def write_start(store: Path, date: str, record: StartRecord) -> None:
    """Write the start record of one trial, one time."""
    path = trial_dir(store, date, record.trial_id) / _START_FILE
    _check_start(record, str(path))
    write_once_json(path, asdict(record))


def read_start_or_none(store: Path, date: str,
                       trial_id: str) -> StartRecord | None:
    path = trial_dir(store, date, trial_id) / _START_FILE
    raw = _raw(path, StartRecord, trial_id)
    if raw is None:
        return None
    record = StartRecord(**raw)
    _check_start(record, str(path))
    return record


def write_send(store: Path, date: str, record: SendRecord) -> None:
    """Write the send record of one trial, one time.

    A second write raises StoreError: one trial has one send. The
    caller holds the write lock, because the chain fields of this send
    follow the send before it.
    """
    path = trial_dir(store, date, record.trial_id) / _SEND_FILE
    _check_send(record, str(path))
    write_once_json(path, asdict(record))


def read_send_or_none(store: Path, date: str,
                      trial_id: str) -> SendRecord | None:
    path = trial_dir(store, date, trial_id) / _SEND_FILE
    raw = _raw(path, SendRecord, trial_id)
    if raw is None:
        return None
    record = SendRecord(**raw)
    _check_send(record, str(path))
    return record


def write_secret(store: Path, date: str, trial_id: str, nonce: str) -> None:
    """Write the nonce of one trial, one time, before its send record.

    No answer reads this file before the result record is there (spec
    IM1 section 12.2).
    """
    _digest(nonce, "nonce")
    write_once_json(trial_dir(store, date, trial_id) / _SECRET_FILE,
                    {"trial_id": trial_id, "nonce": nonce})


def read_secret_or_none(store: Path, date: str, trial_id: str) -> str | None:
    """The stored nonce of one trial, or None."""
    path = trial_dir(store, date, trial_id) / _SECRET_FILE
    raw = read_json_or_none(path)
    if raw is None:
        return None
    if set(raw) != {"trial_id", "nonce"} or raw["trial_id"] != trial_id:
        raise StoreError(f"{path}: not the secret record of {trial_id}")
    _digest(raw["nonce"], f"{path}.nonce")
    return raw["nonce"]


def write_result(store: Path, date: str, record: ResultRecord,
                 commitment: str) -> None:
    """Write the result record of one trial, one time.

    commitment is the commitment of the stored send. A nonce that does
    not agree with it raises, thus no result with a changed nonce
    gets to the store.
    """
    path = trial_dir(store, date, record.trial_id) / _RESULT_FILE
    _check_result(record, str(path))
    if instant_commitment(record.trial_id, record.nonce) != commitment:
        raise StoreError(f"{path}: the nonce does not agree with the "
                         "commitment of the send")
    value = asdict(record)
    value["target_proof"] = list(record.target_proof)
    write_once_json(path, value)


def read_result_or_none(store: Path, date: str,
                        trial_id: str) -> ResultRecord | None:
    path = trial_dir(store, date, trial_id) / _RESULT_FILE
    raw = _raw(path, ResultRecord, trial_id)
    if raw is None:
        return None
    proof = raw["target_proof"]
    if not isinstance(proof, list):
        raise StoreError(f"{path}.target_proof: expected proof steps")
    record = ResultRecord(**{**raw, "target_proof": tuple(proof)})
    _check_result(record, str(path))
    return record


def list_dates(store: Path) -> tuple[str, ...]:
    """The dates with a trial directory, the earliest first."""
    root = instant_dir(store)
    if not root.is_dir():
        return ()
    return tuple(sorted(entry.name for entry in root.iterdir()
                        if entry.is_dir()
                        and _DATE_RULE.fullmatch(entry.name)))


def list_trials(store: Path, date: str) -> tuple[str, ...]:
    """The trial identifiers of one date, sorted."""
    check_date(date, "date")
    root = instant_dir(store) / date
    if not root.is_dir():
        return ()
    return tuple(sorted(entry.name for entry in root.iterdir()
                        if entry.is_dir()
                        and _TRIAL_RULE.fullmatch(entry.name)))


@contextmanager
def instant_write_lock(store: Path) -> Iterator[None]:
    """Hold the write lock of the instant sends: an exclusive file lock.

    The send path holds it from the read of the clock to the write of
    the send record. The sends thus get their chain positions one at a
    time, and the time of a send is not earlier than the time of the
    send before it.
    """
    import fcntl

    directory = instant_dir(store)
    directory.mkdir(parents=True, exist_ok=True)
    handle = os.open(directory / ".write.lock", os.O_RDWR | os.O_CREAT,
                     0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)
