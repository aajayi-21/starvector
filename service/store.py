"""The permanent trial store: days, submissions, trial rows.

Spec: S1 (in docs/specs/) section 5. The store is not a cache -
nothing in it is rebuildable from elsewhere (Rule 4). Submissions
and trial rows are one-write files: the writer makes them with an
atomic, refusing primitive, and no code path edits them. The day
record has one sanctioned edit path, the guarded status move.
"""

import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from core.canonical import JsonValue, canonical_json_pretty, sha256_hex

# "closing" sits between "open" and "closed": the close moves the day
# to it before the scores start, thus a send that arrives while the
# encoder works meets a day that refuses it (spec BR1 section 3).
DAY_STATUSES = ("open", "closing", "closed", "revealed")
PLAYER_STATUSES = ("active", "revoked")

# The account limits (spec A1 in docs/specs/, D1 and D2 as ruled
# 2026-08-21).
DESCRIPTION_LIMIT = 500
AVATAR_BYTE_CAP = 1_048_576

# The rules below match the full value with fullmatch. The dollar
# sign also matches before a newline at the end, thus a changed
# value with a newline at its end gets through a re.match check and
# then names a file. The server configuration reader had the same
# hole on closes_at_utc.
_DAY_RULE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The player name becomes a file name below store/players/, thus
# its shape is the shape the server configuration pins. The
# alphabet holds no dot, and that is what makes the invite token's
# one separator unambiguous (spec M1 in docs/specs/, section 4).
_PLAYER_RULE = re.compile(r"[a-z0-9-]{1,64}")
_TOKEN_HASH_RULE = re.compile(r"[0-9a-f]{64}")

_DISPLAY_NAME_LIMIT = 32

_DAY_FIELDS = ("day", "trial_code", "target_id", "pick_seed", "secret",
               "commitment",
               "scoring_config_path", "scoring_config_hash",
               "preparation_version_id", "status", "opened_at", "closed_at",
               "revealed_at")

_PLAYER_FIELDS = ("player", "display_name", "token_hash", "created_at",
                  "status")

_ACCOUNT_FIELDS = ("player", "description", "avatar_hash", "updated_at")

_README = """\
# The trial store

This directory is the permanent record of play: day records, raw
player submissions, and trial rows (spec S1 in docs/specs/,
section 5). It is not a cache - nothing here is rebuildable from
elsewhere, and Rule 4 of CLAUDE.md applies: raw submissions are
stored forever. Keep it in every backup. The directory sits in
.gitignore because play records are data, not code.

sessions/ and device-codes/ hold sign-in credentials, not play
records: deleting them signs devices out and loses no play.
rollover/ holds the automatic days' pause, their run records, and
their lock: operations records, and not play records either.
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


@dataclass(frozen=True, slots=True)
class AccountRecord:
    """The stored account facts of one player (spec A1 section 3).

    The player's own mutable document: the description and the
    avatar digest. It is a raw fact of play and not a cache
    (Rule 4). It is also the third record class: submissions and
    trial rows are one-write, the day record has one guarded move,
    and this document is replaced as one unit through
    write_account_record. A missing file reads as the empty
    account, not an error.
    """

    player: str
    description: str
    avatar_hash: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class PlayerRecord:
    """The stored facts of one player (spec M1 section 4).

    player is the store key, and it is the identity that submissions
    and trial rows hold today. A mint for a name that plays thus
    adopts that history and no stored record moves. display_name is
    the board label of the records before spec A2. From that spec the
    boards read player, and a new record writes the name there too.

    token_hash is the digest of an invite. The invite is gone (spec A2
    ruling 2): a new record holds None, and an earlier digest stays in
    its record and opens nothing.
    """

    player: str
    display_name: str
    token_hash: str | None
    created_at: str
    status: str


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
        if entry.is_dir() and _DAY_RULE.fullmatch(entry.name)))


def latest_day(store: Path) -> str | None:
    """The most recent stored day, or None (S1 section 14a, OP7)."""
    days = list_days(store)
    return days[-1] if days else None


def _temporary_sibling(path: Path) -> Path:
    """A new, empty temporary file adjacent to path, unique to this write.

    mkstemp names it, thus two writers of one destination do not share
    a temporary file, and one writer cannot read the half-written bytes
    of the other. The name ends in .tmp, and the directory readers skip
    it.
    """
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".",
                                    suffix=".tmp")
    os.close(handle)
    return Path(name)


def _write_synced(path: Path, data: bytes) -> None:
    """Write bytes to a file, and sync them to the disk."""
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _sync_directory(directory: Path) -> None:
    """Sync a directory, thus a new name in it survives a power cut."""
    handle = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def write_once_json(path: Path, value: JsonValue) -> None:
    """Write one JSON document atomically, refusing a second write.

    The document lands in a temporary sibling, and an atomic claim
    then takes the destination - a primitive that refuses an
    existing file - thus two racing writers get one file and one
    StoreError, with no half-written file in each outcome. Each write
    has its own sibling, thus two racing writers cannot break the
    document of the other before the claim.

    The bytes go to the disk before the claim and the name after it
    (spec PL1 section 5): a power cut leaves the record full or
    missing, and a torn permanent record can stop each close of its day.
    """
    temporary = _temporary_sibling(path)
    try:
        _write_synced(temporary,
                      (canonical_json_pretty(value) + "\n").encode("utf-8"))
        os.link(temporary, path)
        _sync_directory(path.parent)
    except FileExistsError as error:
        raise StoreError(
            f"{path}: the store is one-write and the file exists") from error
    finally:
        temporary.unlink(missing_ok=True)


def _replace_json(path: Path, value: JsonValue) -> None:
    """Replace one JSON document atomically, last writer wins.

    The bytes are the ones write_json_pretty writes. The difference is
    the temporary file: write_json_pretty names one fixed sibling, and
    two processes that move one record at the same moment can collide
    on it. Each write here has its own.
    """
    text = canonical_json_pretty(value) + "\n"
    _write_bytes_replacing(path, text.encode("utf-8"))


@contextmanager
def day_write_lock(store: Path, day: str) -> Iterator[None]:
    """Hold the day's write lock: an exclusive advisory file lock.

    The send path holds it for its last status check and its write,
    and the close holds it for the move to "closing". A send thus
    lands before the close reads the submissions, or it meets the
    moved status and refuses. The lock is a file lock, thus it also
    covers a close from a second process - the console unit or the
    command line - and not only a second thread.
    """
    import fcntl

    directory = day_dir(store, day)
    directory.mkdir(parents=True, exist_ok=True)
    handle = os.open(directory / ".write.lock", os.O_RDWR | os.O_CREAT,
                     0o644)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


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
        if isinstance(raw, dict) \
                and set(_DAY_FIELDS) - set(raw) == {"trial_code"} \
                and set(raw) <= set(_DAY_FIELDS):
            raise StoreError(
                f"{path}: a day record from before the section 14b "
                "trial-code amendment - run `uv run python -m "
                "service.day migrate` one time to backfill it")
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
    if not re.fullmatch(r"[A-Z0-9]{6}", raw["trial_code"]):
        raise StoreError(
            f"{path}.trial_code: expected six characters, A-Z and 0-9")
    return DayRecord(**raw)


def update_day_status(store: Path, day: str, *, expect_status: str,
                      new_status: str, timestamp_field: str | None,
                      timestamp: str | None) -> DayRecord:
    """The one sanctioned day-record edit: the guarded status move.

    Reads the stored record again, refuses unless its status equals
    expect_status (the out-of-sequence guard), then writes the moved
    record atomically. Submissions and trial rows have no edit path
    at all (R2).

    The move to "closing" sets no timestamp: timestamp_field and
    timestamp are then None, and the record keeps its field set.
    """
    if new_status not in DAY_STATUSES:
        raise StoreError(f"unknown status: {new_status!r}")
    if timestamp_field is None:
        if timestamp is not None:
            raise StoreError("a timestamp with no timestamp field")
    elif timestamp_field not in ("closed_at", "revealed_at"):
        raise StoreError(f"unknown timestamp field: {timestamp_field!r}")
    record = read_day_record(store, day)
    if record.status != expect_status:
        raise StoreError(
            f"day {day} has status {record.status!r} and the move needs "
            f"{expect_status!r}")
    moved = replace(record, status=new_status) if timestamp_field is None \
        else replace(record, status=new_status,
                     **{timestamp_field: timestamp})
    _replace_json(day_record_path(store, day), _day_to_value(moved))
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


def count_submissions(store: Path, day: str) -> int:
    """The number of stored submissions for one day, zero when none.

    The count rule of list_submissions without the sorted names: the
    home page reads it on each poll of an open tab, and it needs the
    number alone (spec H1 section 3). A `.tmp` file is a write that
    has not ended and is not a send. Practice trials are not in the
    folder, so they are not in the count.
    """
    root = day_dir(store, day) / "submissions"
    if not root.is_dir():
        return 0
    with os.scandir(root) as entries:
        return sum(1 for entry in entries
                   if entry.name.endswith(".json") and entry.is_file())


def check_player_name(value: object, where: str) -> None:
    """Refuse a player name that is not a legal store key."""
    if not isinstance(value, str) or not _PLAYER_RULE.fullmatch(value):
        raise StoreError(
            f"{where}: expected 1 to 64 characters, a-z, 0-9, and the "
            f"hyphen, got {value!r}")


def check_display_name(value: object, where: str) -> None:
    """Refuse a board label that is not 1 to 32 printable characters.

    Printable is str.isprintable(): each Unicode category but Other
    and Separator, and the ASCII space stays. The rule thus refuses
    the control characters, the zero-width and format characters,
    and the direction overrides that make one label look the same
    as a different one. The count is in code points and not in
    bytes, because the store writes UTF-8 with no escapes and a
    byte cap becomes a different cap for each script. The rule
    refuses a space at the start or the end for the same
    impersonation cause.
    """
    if not isinstance(value, str):
        raise StoreError(f"{where}: expected a string, got {value!r}")
    if not 1 <= len(value) <= _DISPLAY_NAME_LIMIT:
        raise StoreError(
            f"{where}: expected 1 to {_DISPLAY_NAME_LIMIT} characters, "
            f"got {len(value)}")
    if not value.isprintable():
        raise StoreError(
            f"{where}: the label holds a control or a format character")
    if value != value.strip():
        raise StoreError(f"{where}: the label starts or ends with a space")


def players_dir(store: Path) -> Path:
    return store / "players"


def player_record_path(store: Path, player: str) -> Path:
    return players_dir(store) / f"{player}.json"


def any_player(store: Path) -> bool:
    """The store holds one player record or more - the access switch.

    Ruling 7 of spec M1: with no record the server keeps today's
    behavior, and the first mint turns access control on. The walk
    stops at the first entry, thus its cost does not become larger
    with the player count and a handler can use it. This function
    reads the directory each time and caches nothing, because a
    record that an operator puts back by hand must count
    immediately.
    """
    root = players_dir(store)
    if not root.is_dir():
        return False
    for entry in root.iterdir():
        if entry.is_file() and entry.name.endswith(".json"):
            return True
    return False


def list_players(store: Path) -> tuple[str, ...]:
    """The player names with a stored record, ascending."""
    root = players_dir(store)
    if not root.is_dir():
        return ()
    return tuple(sorted(
        entry.name[:-5] for entry in root.iterdir()
        if entry.is_file() and entry.name.endswith(".json")
        and not entry.name.endswith(".tmp")))


def _player_to_value(record: PlayerRecord) -> dict[str, JsonValue]:
    return {
        "player": record.player,
        "display_name": record.display_name,
        "token_hash": record.token_hash,
        "created_at": record.created_at,
        "status": record.status,
    }


def _check_player_record(record: PlayerRecord) -> None:
    """Refuse a record the store must not write."""
    check_player_name(record.player, "player")
    check_display_name(record.display_name, "display_name")
    if record.token_hash is not None and (
            not isinstance(record.token_hash, str)
            or not _TOKEN_HASH_RULE.fullmatch(record.token_hash)):
        raise StoreError(
            "token_hash: expected 64 lowercase hex characters or null, "
            f"got {record.token_hash!r}")
    if not record.created_at:
        raise StoreError("created_at: expected a non-empty string")


def write_player_record(store: Path, record: PlayerRecord) -> None:
    """Write a new player record, one time.

    The write rides the one-write primitive, thus a second record for
    the name raises. Sign-up and the dev door make records (spec A2).
    """
    if record.status != "active":
        raise StoreError(
            f"a new player record must have status 'active', got "
            f"{record.status!r}")
    _check_player_record(record)
    write_once_json(player_record_path(store, record.player),
                    _player_to_value(record))


def read_player_record(store: Path, player: str) -> PlayerRecord:
    """Read and validate one stored player record, strict."""
    import json

    check_player_name(player, "player")
    path = player_record_path(store, player)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"{path}: cannot read the player record: {error}") \
            from error
    if not isinstance(raw, dict) or set(raw) != set(_PLAYER_FIELDS):
        raise StoreError(
            f"{path}: the player record must have the fields "
            f"{sorted(_PLAYER_FIELDS)}")
    for name in _PLAYER_FIELDS:
        if name == "token_hash" and raw[name] is None:
            continue
        if not isinstance(raw[name], str) or not raw[name]:
            raise StoreError(f"{path}.{name}: expected a non-empty string")
    if raw["status"] not in PLAYER_STATUSES:
        raise StoreError(
            f"{path}.status: expected one of {list(PLAYER_STATUSES)}")
    if raw["player"] != player:
        raise StoreError(
            f"{path}.player: the record names {raw['player']!r} and the "
            f"file names {player!r}")
    check_display_name(raw["display_name"], f"{path}.display_name")
    if raw["token_hash"] is not None \
            and not _TOKEN_HASH_RULE.fullmatch(raw["token_hash"]):
        raise StoreError(
            f"{path}.token_hash: expected 64 lowercase hex characters "
            "or null")
    return PlayerRecord(**raw)


def read_player_or_none(store: Path, player: str) -> PlayerRecord | None:
    """One stored player record, or None when the file is not there.

    The handler's reader. An unknown name is an ordinary answer,
    which the caller turns into the constant refusal, and a stored
    record that does not parse is not an ordinary answer.
    """
    if not isinstance(player, str) or not _PLAYER_RULE.fullmatch(player):
        return None
    if not player_record_path(store, player).is_file():
        return None
    return read_player_record(store, player)


def set_player_status(store: Path, player: str, *, expect_status: str,
                      new_status: str) -> PlayerRecord:
    """The guarded player edit: the status move.

    Revoke moves 'active' to 'revoked' and the opposite move puts
    it back. A move that repeats raises and names the two statuses,
    thus the command is not silently a no-operation.
    """
    if expect_status not in PLAYER_STATUSES:
        raise StoreError(f"unknown status: {expect_status!r}")
    if new_status not in PLAYER_STATUSES:
        raise StoreError(f"unknown status: {new_status!r}")
    record = read_player_record(store, player)
    if record.status != expect_status:
        raise StoreError(
            f"player {player} has status {record.status!r} and the move "
            f"needs {expect_status!r}")
    moved = replace(record, status=new_status)
    _replace_json(player_record_path(store, player), _player_to_value(moved))
    return moved


def check_description(value: object, where: str) -> None:
    """Refuse a description that breaks the account text rule.

    The display-name discipline, grown for long text (spec A1
    section 3, D1): 0 to 500 code points, printable characters
    with the newline as the one control character permitted, and
    no whitespace at the start or the end. Empty text is legal -
    an account with nothing written is the usual condition.
    """
    if not isinstance(value, str):
        raise StoreError(f"{where}: expected a string, got {value!r}")
    if len(value) > DESCRIPTION_LIMIT:
        raise StoreError(
            f"{where}: expected at most {DESCRIPTION_LIMIT} characters, "
            f"got {len(value)}")
    for line in value.split("\n"):
        if not line.isprintable():
            raise StoreError(
                f"{where}: the text holds a control or a format character")
    if value != value.strip():
        raise StoreError(f"{where}: the text starts or ends with whitespace")


def avatar_media_type(data: bytes) -> str | None:
    """The avatar media type from magic bytes, or None.

    The accepted set is the four kinds of spec A1 D2: PNG, JPEG,
    WebP, GIF. No header counts here - the stored bytes alone do.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def accounts_dir(store: Path) -> Path:
    """The account directory - its own, not store/players/.

    list_players and any_player read each .json name below
    store/players/ as a player, thus a second file class there
    becomes a phantom player name (spec A1 section 3).
    """
    return store / "accounts"


def account_record_path(store: Path, player: str) -> Path:
    return accounts_dir(store) / f"{player}.json"


def avatar_path(store: Path, player: str) -> Path:
    return accounts_dir(store) / f"{player}.avatar"


def _account_to_value(record: AccountRecord) -> dict[str, JsonValue]:
    return {
        "player": record.player,
        "description": record.description,
        "avatar_hash": record.avatar_hash,
        "updated_at": record.updated_at,
    }


def _check_account_record(record: AccountRecord) -> None:
    """Refuse an account record the store must not write."""
    check_player_name(record.player, "player")
    check_description(record.description, "description")
    if record.avatar_hash is not None \
            and not _TOKEN_HASH_RULE.fullmatch(record.avatar_hash):
        raise StoreError(
            "avatar_hash: expected 64 lowercase hex characters or null")
    if not record.updated_at:
        raise StoreError("updated_at: expected a non-empty string")


def _write_bytes_replacing(path: Path, data: bytes) -> None:
    """Replace one file atomically through its own temporary sibling.

    Not write_bytes_atomic: that helper names one fixed .tmp
    sibling, thus two concurrent writers of the same destination
    collide on it - the loser's os.replace raises and a reader can
    read a torn temporary. Each write here gets its own sibling
    from mkstemp, thus concurrent writers end in last-writer-wins
    with complete documents in each interleaving. The bytes go to the
    disk before the replace and the name after it (spec PL1 section 5).
    """
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent,
                                         prefix=path.name + ".",
                                         suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as sibling:
            sibling.write(data)
            sibling.flush()
            os.fsync(sibling.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_account_record(store: Path, record: AccountRecord) -> None:
    """Write one account record, replacing the earlier one.

    The document lands in its own temporary sibling and os.replace
    takes the destination - atomic, thus a torn document cannot
    occur, also with two concurrent writers. This is the account
    record's one edit path (spec A1 section 3).
    """
    _check_account_record(record)
    text = canonical_json_pretty(_account_to_value(record)) + "\n"
    _write_bytes_replacing(account_record_path(store, record.player),
                           text.encode("utf-8"))


def read_account_or_none(store: Path, player: str) -> AccountRecord | None:
    """One stored account record, or None when the file is not there.

    None reads as the empty account. A stored record that does not
    validate is not an ordinary answer and raises.
    """
    import json

    if not isinstance(player, str) or not _PLAYER_RULE.fullmatch(player):
        return None
    path = account_record_path(store, player)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(
            f"{path}: cannot read the account record: {error}") from error
    if not isinstance(raw, dict) or set(raw) != set(_ACCOUNT_FIELDS):
        raise StoreError(
            f"{path}: the account record must have the fields "
            f"{sorted(_ACCOUNT_FIELDS)}")
    if raw["player"] != player:
        raise StoreError(
            f"{path}.player: the record names {raw['player']!r} and the "
            f"file names {player!r}")
    check_description(raw["description"], f"{path}.description")
    if raw["avatar_hash"] is not None and (
            not isinstance(raw["avatar_hash"], str)
            or not _TOKEN_HASH_RULE.fullmatch(raw["avatar_hash"])):
        raise StoreError(
            f"{path}.avatar_hash: expected 64 lowercase hex characters "
            "or null")
    if not isinstance(raw["updated_at"], str) or not raw["updated_at"]:
        raise StoreError(f"{path}.updated_at: expected a non-empty string")
    return AccountRecord(**raw)


def _account_base(store: Path, player: str,
                  timestamp: str) -> AccountRecord:
    """The stored account, or the empty one - the edit starting point."""
    found = read_account_or_none(store, player)
    if found is not None:
        return found
    return AccountRecord(player=player, description="", avatar_hash=None,
                         updated_at=timestamp)


def set_account_description(store: Path, player: str, text: str, *,
                            timestamp: str) -> AccountRecord:
    """Store one player's description and answer the moved record."""
    check_player_name(player, "player")
    check_description(text, "description")
    moved = replace(_account_base(store, player, timestamp),
                    description=text, updated_at=timestamp)
    write_account_record(store, moved)
    return moved


def write_avatar_bytes(store: Path, player: str, data: bytes) -> str:
    """Store one avatar and answer its sha256 digest.

    The two refusals come in a fixed sequence (spec A1 section 9):
    the cap first, the magic bytes second. The bytes land in a
    temporary sibling and os.replace takes the destination, thus a
    torn file cannot occur.
    """
    check_player_name(player, "player")
    if not isinstance(data, bytes):
        raise StoreError("avatar: expected bytes")
    if len(data) > AVATAR_BYTE_CAP:
        raise StoreError(
            f"avatar: expected at most {AVATAR_BYTE_CAP} bytes, "
            f"got {len(data)}")
    if avatar_media_type(data) is None:
        raise StoreError(
            "avatar: the bytes are not a PNG, JPEG, WebP, or GIF image")
    _write_bytes_replacing(avatar_path(store, player), data)
    return sha256_hex(data)


def read_avatar_or_none(store: Path, player: str) -> bytes | None:
    """One stored avatar, or None - one answer covers a player with
    no picture and a name with no record, thus the serving path
    holds no roster oracle (spec A1 section 3)."""
    if not isinstance(player, str) or not _PLAYER_RULE.fullmatch(player):
        return None
    path = avatar_path(store, player)
    if not path.is_file():
        return None
    return path.read_bytes()


def set_account_avatar(store: Path, player: str, data: bytes, *,
                       timestamp: str) -> AccountRecord:
    """Store one avatar and move the account record after it.

    The bytes land first and the record follows (spec A1
    section 3). A stop between the two gives a stale avatar_hash -
    a cache key and not a claim - and the next write heals it.
    """
    digest = write_avatar_bytes(store, player, data)
    moved = replace(_account_base(store, player, timestamp),
                    avatar_hash=digest, updated_at=timestamp)
    write_account_record(store, moved)
    return moved


def clear_account_avatar(store: Path, player: str, *,
                         timestamp: str) -> AccountRecord:
    """Remove one avatar and move the account record after it.

    The same sequence as set_account_avatar: the bytes go first
    and the record follows. Clearing an account with no picture is
    legal and answers the moved record all the same.
    """
    check_player_name(player, "player")
    avatar_path(store, player).unlink(missing_ok=True)
    moved = replace(_account_base(store, player, timestamp),
                    avatar_hash=None, updated_at=timestamp)
    write_account_record(store, moved)
    return moved


# -- sessions and device codes (spec BR1 section 4) --------------------
#
# Two credential classes, in directories of their own. The two are
# not play records: a session or a code can be deleted, and a deleted one
# stops at its next read. The file name of each is the digest of its
# secret, thus the store holds no secret and a read finds a record by
# its digest alone, with no walk.

_SESSION_FIELDS = ("player", "label", "created_at")
_DEVICE_CODE_FIELDS = ("player", "created_at", "expires_at")
_SESSION_LABEL_LIMIT = 40


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One signed-in device of one player (spec BR1 section 4).

    label names the device on the player's account screen ("Safari on
    iPhone"). created_at starts the session's fixed life.
    """

    player: str
    label: str
    created_at: str


@dataclass(frozen=True, slots=True)
class DeviceCodeRecord:
    """One code that signs a second device in, one time (BR1 section 4)."""

    player: str
    created_at: str
    expires_at: str


def _check_digest(value: object, where: str) -> str:
    if not isinstance(value, str) or not _TOKEN_HASH_RULE.fullmatch(value):
        raise StoreError(f"{where}: expected 64 lowercase hex characters")
    return value


def sessions_dir(store: Path, player: str) -> Path:
    """The player's session directory. Not below store/players/: a
    second file class there reads as a phantom player (spec A1)."""
    return store / "sessions" / player


def session_path(store: Path, player: str, digest: str) -> Path:
    return sessions_dir(store, player) / f"{digest}.json"


def _session_to_value(record: SessionRecord) -> dict[str, JsonValue]:
    return {"player": record.player, "label": record.label,
            "created_at": record.created_at}


def write_session_record(store: Path, digest: str,
                         record: SessionRecord) -> None:
    """Store one new session - one write, the digest as the name."""
    check_player_name(record.player, "player")
    _check_digest(digest, "session digest")
    if not isinstance(record.label, str) \
            or not 1 <= len(record.label) <= _SESSION_LABEL_LIMIT \
            or not record.label.isprintable():
        raise StoreError(
            f"label: expected 1 to {_SESSION_LABEL_LIMIT} printable "
            "characters")
    if not record.created_at:
        raise StoreError("created_at: expected a non-empty string")
    write_once_json(session_path(store, record.player, digest),
                    _session_to_value(record))


def _read_record(path: Path, fields: tuple[str, ...]) -> dict:
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"{path}: cannot read: {error}") from error
    if not isinstance(raw, dict) or set(raw) != set(fields):
        raise StoreError(f"{path}: expected the fields {sorted(fields)}")
    for name in fields:
        if not isinstance(raw[name], str) or not raw[name]:
            raise StoreError(f"{path}.{name}: expected a non-empty string")
    return raw


def read_session_or_none(store: Path, player: str,
                         digest: str) -> SessionRecord | None:
    """One stored session, or None when there is none by that digest.

    A name or a digest of a bad shape is None too: the caller
    turns each of them into the one constant refusal.
    """
    if not isinstance(player, str) or not _PLAYER_RULE.fullmatch(player):
        return None
    if not isinstance(digest, str) or not _TOKEN_HASH_RULE.fullmatch(digest):
        return None
    path = session_path(store, player, digest)
    if not path.is_file():
        return None
    raw = _read_record(path, _SESSION_FIELDS)
    if raw["player"] != player:
        raise StoreError(f"{path}.player: the record names {raw['player']!r}")
    return SessionRecord(**raw)


def list_sessions(store: Path,
                  player: str) -> tuple[tuple[str, SessionRecord], ...]:
    """The player's sessions as (digest, record), oldest first."""
    check_player_name(player, "player")
    root = sessions_dir(store, player)
    if not root.is_dir():
        return ()
    found = []
    for entry in root.iterdir():
        name = entry.name
        if not (entry.is_file() and name.endswith(".json")):
            continue
        digest = name[:-5]
        if not _TOKEN_HASH_RULE.fullmatch(digest):
            continue
        record = read_session_or_none(store, player, digest)
        if record is not None:
            found.append((digest, record))
    return tuple(sorted(found, key=lambda pair: (pair[1].created_at,
                                                 pair[0])))


def delete_session(store: Path, player: str, digest: str) -> bool:
    """Remove one session, and say if there was one to remove."""
    check_player_name(player, "player")
    _check_digest(digest, "session digest")
    try:
        session_path(store, player, digest).unlink()
    except FileNotFoundError:
        return False
    return True


def delete_player_sessions(store: Path, player: str, *,
                           keep: str | None = None) -> int:
    """Remove each session of one player but keep, and count them."""
    removed = 0
    for digest, _record in list_sessions(store, player):
        if digest != keep and delete_session(store, player, digest):
            removed += 1
    return removed


def device_codes_dir(store: Path) -> Path:
    return store / "device-codes"


def device_code_path(store: Path, digest: str) -> Path:
    return device_codes_dir(store) / f"{digest}.json"


def write_device_code(store: Path, digest: str,
                      record: DeviceCodeRecord) -> None:
    """Store one new device code - one write, the digest as the name."""
    check_player_name(record.player, "player")
    _check_digest(digest, "device code digest")
    if not record.created_at or not record.expires_at:
        raise StoreError("a device code needs its two timestamps")
    write_once_json(device_code_path(store, digest),
                    {"player": record.player,
                     "created_at": record.created_at,
                     "expires_at": record.expires_at})


def claim_device_code(store: Path, digest: str) -> DeviceCodeRecord | None:
    """Remove one device code from the store, and answer it.

    The read comes first and the removal second, and the removal is
    the claim: of two redeemers that read the same code, one removes
    the file and the other meets FileNotFoundError and gets None. A
    code thus signs one device in at most. The caller checks the
    expiry of the claimed record.
    """
    if not isinstance(digest, str) or not _TOKEN_HASH_RULE.fullmatch(digest):
        return None
    path = device_code_path(store, digest)
    if not path.is_file():
        return None
    raw = _read_record(path, _DEVICE_CODE_FIELDS)
    try:
        path.unlink()
    except FileNotFoundError:
        return None
    check_player_name(raw["player"], f"{path}.player")
    return DeviceCodeRecord(**raw)


def list_device_codes(store: Path) -> tuple[tuple[str, DeviceCodeRecord],
                                             ...]:
    """Each stored device code as (digest, record) - for the prune."""
    root = device_codes_dir(store)
    if not root.is_dir():
        return ()
    found = []
    for entry in sorted(root.iterdir()):
        name = entry.name
        if not (entry.is_file() and name.endswith(".json")):
            continue
        digest = name[:-5]
        if not _TOKEN_HASH_RULE.fullmatch(digest):
            continue
        found.append((digest, DeviceCodeRecord(
            **_read_record(entry, _DEVICE_CODE_FIELDS))))
    return tuple(found)


def remove_device_code(store: Path, digest: str) -> bool:
    """Remove one device code, and say if it was there."""
    _check_digest(digest, "device code digest")
    try:
        device_code_path(store, digest).unlink()
    except FileNotFoundError:
        return False
    return True


# -- credentials and name claims (spec A2 section 7) --------------------
#
# Two record classes, each in a directory of its own. The credential
# record is the one record that sign-in alone opens: no board, no
# index, and no export reads its directory. The name claim makes one
# name of two names with one folded shape.

_CREDENTIAL_FIELDS = (
    "player", "password_digest", "password_set_at", "recovery_digest",
    "recovery_issued_at", "operator_digest", "operator_issued_at",
    "operator_usable_at", "updated_at")
_CLAIM_FIELDS = ("folded", "player", "claimed_at")
_FOLDED_RULE = re.compile(r"[a-z0-9]{1,64}")


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    """What a player signs in and recovers with (spec A2 section 7.1).

    password_digest is the text of the password digest, and the store
    does not read into it. recovery_digest is the sha256 hex of the
    player's own recovery code. The three operator fields are the
    operator's code, which has its own slot and a time from which it
    works (spec A2 section 6.1). A part that is not set is None, and
    the fields of one part are set together.
    """

    player: str
    password_digest: str | None
    password_set_at: str | None
    recovery_digest: str | None
    recovery_issued_at: str | None
    operator_digest: str | None
    operator_issued_at: str | None
    operator_usable_at: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class NameClaim:
    """One claimed folded shape and the player that holds it."""

    folded: str
    player: str
    claimed_at: str


def credentials_dir(store: Path) -> Path:
    """The credential directory. Not below store/players/: a second
    file class there reads as a phantom player (spec A1 section 3)."""
    return store / "credentials"


def credential_record_path(store: Path, player: str) -> Path:
    return credentials_dir(store) / f"{player}.json"


def any_credential(store: Path) -> bool:
    """The store holds one credential record or more. The walk stops
    at the first entry."""
    root = credentials_dir(store)
    if not root.is_dir():
        return False
    for entry in root.iterdir():
        if entry.is_file() and entry.name.endswith(".json"):
            return True
    return False


@contextmanager
def credential_lock(store: Path, player: str) -> Iterator[None]:
    """Hold the write lock of one player's credential record.

    Each credential move is a read, a check, and a write. Two
    recoveries with one code must not each read the code as live, thus
    a move holds this exclusive file lock for its three steps. It is a
    file lock, thus it also covers the operator's command line.
    """
    import fcntl

    check_player_name(player, "player")
    directory = credentials_dir(store)
    directory.mkdir(parents=True, exist_ok=True)
    handle = os.open(directory / f".{player}.lock", os.O_RDWR | os.O_CREAT,
                     0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def _credential_to_value(record: CredentialRecord) -> dict[str, JsonValue]:
    return {name: getattr(record, name) for name in _CREDENTIAL_FIELDS}


def _check_part(where: str, values: tuple[object, ...]) -> None:
    """The fields of one part are each a non-empty string or each None."""
    if all(value is None for value in values):
        return
    if not all(isinstance(value, str) and value for value in values):
        raise StoreError(
            f"{where}: the fields of this part are set together, each a "
            "non-empty string, or each null")


def _check_credential_record(record: CredentialRecord,
                             where: str = "credential") -> None:
    """Refuse a credential record the store must not hold."""
    check_player_name(record.player, f"{where}.player")
    _check_part(f"{where}.password",
                (record.password_digest, record.password_set_at))
    _check_part(f"{where}.recovery",
                (record.recovery_digest, record.recovery_issued_at))
    _check_part(f"{where}.operator",
                (record.operator_digest, record.operator_issued_at,
                 record.operator_usable_at))
    for name in ("recovery_digest", "operator_digest"):
        value = getattr(record, name)
        if value is not None and not _TOKEN_HASH_RULE.fullmatch(value):
            raise StoreError(
                f"{where}.{name}: expected 64 lowercase hex characters "
                "or null")
    if not isinstance(record.updated_at, str) or not record.updated_at:
        raise StoreError(f"{where}.updated_at: expected a non-empty string")


def write_credential_record(store: Path, record: CredentialRecord) -> None:
    """Write one credential record, replacing the earlier one.

    The caller holds credential_lock for the read before this write.
    The file is readable by its owner alone.
    """
    _check_credential_record(record)
    text = canonical_json_pretty(_credential_to_value(record)) + "\n"
    path = credential_record_path(store, record.player)
    _write_bytes_replacing(path, text.encode("utf-8"))


def read_credential_or_none(store: Path,
                            player: str) -> CredentialRecord | None:
    """One stored credential record, or None when the file is not there.

    None is an ordinary answer: the player has no password and no
    code. A stored record that does not validate raises. It does not
    read as "no password" (spec A2 section 13).
    """
    import json

    if not isinstance(player, str) or not _PLAYER_RULE.fullmatch(player):
        return None
    path = credential_record_path(store, player)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(
            f"{path}: cannot read the credential record: {error}") from error
    if not isinstance(raw, dict) or set(raw) != set(_CREDENTIAL_FIELDS):
        raise StoreError(
            f"{path}: the credential record must have the fields "
            f"{sorted(_CREDENTIAL_FIELDS)}")
    if raw["player"] != player:
        raise StoreError(
            f"{path}.player: the record names {raw['player']!r} and the "
            f"file names {player!r}")
    record = CredentialRecord(**raw)
    _check_credential_record(record, str(path))
    return record


def names_dir(store: Path) -> Path:
    return store / "names"


def name_claim_path(store: Path, folded: str) -> Path:
    return names_dir(store) / f"{folded}.json"


def _check_folded(folded: object, where: str) -> None:
    if not isinstance(folded, str) or not _FOLDED_RULE.fullmatch(folded):
        raise StoreError(
            f"{where}: expected 1 to 64 characters, a-z and 0-9, got "
            f"{folded!r}")


def claim_name(store: Path, claim: NameClaim) -> None:
    """Claim one folded shape for one player, one time.

    The write is the one-write primitive, which refuses a file that is
    there. Of two sign-ups for one folded shape, one gets the claim and
    the other gets StoreError. A claim is not removed (spec A2 section
    4.3).
    """
    _check_folded(claim.folded, "folded")
    check_player_name(claim.player, "player")
    if not claim.claimed_at:
        raise StoreError("claimed_at: expected a non-empty string")
    write_once_json(name_claim_path(store, claim.folded),
                    {"folded": claim.folded, "player": claim.player,
                     "claimed_at": claim.claimed_at})


def read_claim_or_none(store: Path, folded: str) -> NameClaim | None:
    """The claim of one folded shape, or None when nobody holds it.

    The lookup reads one file and walks nothing.
    """
    if not isinstance(folded, str) or not _FOLDED_RULE.fullmatch(folded):
        return None
    path = name_claim_path(store, folded)
    if not path.is_file():
        return None
    raw = _read_record(path, _CLAIM_FIELDS)
    if raw["folded"] != folded:
        raise StoreError(
            f"{path}.folded: the record names {raw['folded']!r} and the "
            f"file names {folded!r}")
    check_player_name(raw["player"], f"{path}.player")
    return NameClaim(**raw)


# -- the records of the public database (spec R1) ------------------------
#
# Four record classes. The consent record says that a player agreed to
# one version of the notice. The start record is the time a player
# opened the drawing screen of a day. The withhold record keeps the
# text and the sketch of one response out of a public snapshot. The
# identifier record is the name that a snapshot shows for a player
# with no username in it. Each one is a raw fact (I4): no other record
# gives it.

_CONSENT_FIELDS = ("player", "notice", "agreed_at")
_START_FIELDS = ("day", "player", "started_at")
_WITHHELD_FIELDS = ("day", "player", "withheld_at", "note")
_IDENTIFIER_FIELDS = ("player", "identifier", "made_at")
_IDENTIFIER_RULE = re.compile(r"anon-[0-9a-f]{16}")
WITHHELD_NOTE_LIMIT = 200


@dataclass(frozen=True, slots=True)
class WithheldRecord:
    """One response that a public snapshot shows with no text and no
    sketch (spec R1 section 9). note is for the operator alone."""

    day: str
    player: str
    withheld_at: str
    note: str


def _check_day(day: object, where: str) -> None:
    if not isinstance(day, str) or not _DAY_RULE.fullmatch(day):
        raise StoreError(f"{where}: expected a day, got {day!r}")


def consent_path(store: Path, player: str, notice: int) -> Path:
    """One file for each player and each notice version. An earlier
    agreement thus stays when a new version gets its own."""
    return store / "consents" / player / f"{notice}.json"


def write_consent(store: Path, player: str, notice: int,
                  agreed_at: str) -> bool:
    """Record that a player agreed to one notice version, one time.

    The answer says if this write made the record. A record that was
    there stays: the first agreement keeps its time.
    """
    check_player_name(player, "player")
    if not isinstance(notice, int) or isinstance(notice, bool) or notice < 1:
        raise StoreError(f"notice: expected a version number, got {notice!r}")
    if not agreed_at:
        raise StoreError("agreed_at: expected a non-empty string")
    try:
        write_once_json(consent_path(store, player, notice),
                        {"player": player, "notice": notice,
                         "agreed_at": agreed_at})
    except StoreError:
        if consent_path(store, player, notice).is_file():
            return False
        raise
    return True


def read_consent_or_none(store: Path, player: str,
                         notice: int) -> dict | None:
    """The consent record of one player and one version, or None.

    A stored record that does not validate raises: it does not read as
    an agreement.
    """
    import json

    if not isinstance(player, str) or not _PLAYER_RULE.fullmatch(player):
        return None
    path = consent_path(store, player, notice)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"{path}: cannot read: {error}") from error
    if not isinstance(raw, dict) or set(raw) != set(_CONSENT_FIELDS) \
            or raw["player"] != player or raw["notice"] != notice \
            or not isinstance(raw["agreed_at"], str) or not raw["agreed_at"]:
        raise StoreError(f"{path}: not the consent record of {player!r} "
                         f"for notice {notice}")
    return raw


def start_path(store: Path, day: str, player: str) -> Path:
    return day_dir(store, day) / "starts" / f"{player}.json"


def write_start(store: Path, day: str, player: str, started_at: str) -> bool:
    """Record the first start of one player on one day, one time.

    The answer says if this write made the record. A second start
    changes nothing (spec R1 section 4).
    """
    _check_day(day, "day")
    check_player_name(player, "player")
    if not started_at:
        raise StoreError("started_at: expected a non-empty string")
    path = start_path(store, day, player)
    if path.is_file():
        return False
    try:
        write_once_json(path, {"day": day, "player": player,
                               "started_at": started_at})
    except StoreError:
        if path.is_file():
            return False
        raise
    return True


def read_start_or_none(store: Path, day: str, player: str) -> str | None:
    """The start time of one player on one day, or None."""
    path = start_path(store, day, player)
    if not path.is_file():
        return None
    raw = _read_record(path, _START_FIELDS)
    if raw["day"] != day or raw["player"] != player:
        raise StoreError(f"{path}: the record names {raw['day']!r} and "
                         f"{raw['player']!r}")
    return raw["started_at"]


def withheld_path(store: Path, day: str, player: str) -> Path:
    return store / "public" / "withheld" / day / f"{player}.json"


def write_withheld(store: Path, record: WithheldRecord) -> None:
    """Withhold one response from the public snapshots, or change the
    note of a withheld one. The stored response does not change."""
    _check_day(record.day, "day")
    check_player_name(record.player, "player")
    if not record.withheld_at:
        raise StoreError("withheld_at: expected a non-empty string")
    if not isinstance(record.note, str) \
            or not 1 <= len(record.note) <= WITHHELD_NOTE_LIMIT \
            or not record.note.isprintable():
        raise StoreError(
            f"note: expected 1 to {WITHHELD_NOTE_LIMIT} printable characters")
    _replace_json(withheld_path(store, record.day, record.player),
                  {"day": record.day, "player": record.player,
                   "withheld_at": record.withheld_at, "note": record.note})


def remove_withheld(store: Path, day: str, player: str) -> bool:
    """Remove one response from the withhold table, and say if it was
    there."""
    _check_day(day, "day")
    check_player_name(player, "player")
    try:
        withheld_path(store, day, player).unlink()
    except FileNotFoundError:
        return False
    return True


def read_withheld_or_none(store: Path, day: str,
                          player: str) -> WithheldRecord | None:
    path = withheld_path(store, day, player)
    if not path.is_file():
        return None
    raw = _read_record(path, _WITHHELD_FIELDS)
    if raw["day"] != day or raw["player"] != player:
        raise StoreError(f"{path}: the record names {raw['day']!r} and "
                         f"{raw['player']!r}")
    return WithheldRecord(**raw)


def list_withheld(store: Path) -> tuple[WithheldRecord, ...]:
    """Each withheld response, by day and then by player."""
    root = store / "public" / "withheld"
    if not root.is_dir():
        return ()
    found = []
    for directory in sorted(root.iterdir()):
        if not (directory.is_dir() and _DAY_RULE.fullmatch(directory.name)):
            continue
        for entry in sorted(directory.iterdir()):
            if entry.is_file() and entry.name.endswith(".json") \
                    and not entry.name.endswith(".tmp"):
                record = read_withheld_or_none(store, directory.name,
                                               entry.name[:-5])
                if record is not None:
                    found.append(record)
    return tuple(found)


def identifier_path(store: Path, player: str) -> Path:
    return store / "public" / "identifiers" / f"{player}.json"


def read_identifier_or_none(store: Path, player: str) -> str | None:
    """The anonymous identifier of one player, or None when there is
    no record."""
    if not isinstance(player, str) or not _PLAYER_RULE.fullmatch(player):
        return None
    path = identifier_path(store, player)
    if not path.is_file():
        return None
    raw = _read_record(path, _IDENTIFIER_FIELDS)
    if raw["player"] != player \
            or not _IDENTIFIER_RULE.fullmatch(raw["identifier"]):
        raise StoreError(f"{path}: not the identifier record of {player!r}")
    return raw["identifier"]


def ensure_identifier(store: Path, player: str, made_at: str,
                      identifier: str | None = None) -> str:
    """The anonymous identifier of one player, made at the first use.

    The identifier is random: it comes from no datum of the player,
    thus no reader can go from it to the username (spec R1 section 8).
    The record is written one time, thus a player has one identifier in
    each snapshot. identifier arrives as an argument for the tests that
    pin one.
    """
    import secrets as _secrets

    check_player_name(player, "player")
    found = read_identifier_or_none(store, player)
    if found is not None:
        return found
    chosen = identifier or f"anon-{_secrets.token_hex(8)}"
    if not _IDENTIFIER_RULE.fullmatch(chosen):
        raise StoreError(f"identifier: expected anon- and 16 hexadecimal "
                         f"characters, got {chosen!r}")
    if not made_at:
        raise StoreError("made_at: expected a non-empty string")
    try:
        write_once_json(identifier_path(store, player),
                        {"player": player, "identifier": chosen,
                         "made_at": made_at})
    except StoreError:
        # A second process made the record between the read and the
        # write. Its identifier is the one.
        found = read_identifier_or_none(store, player)
        if found is None:
            raise
        return found
    return chosen


# The rollover's records (spec BR1 section 7.2): the operator's pause,
# one record for each rollover, and the lock. Operations records, not
# play: removing them loses no play.
ROLLOVER_SOURCES = ("timer", "command-line", "console")
ROLLOVER_OUTCOMES = ("moved", "nothing due", "paused", "failed")
ROLLOVER_STEPS = ("open", "close", "reveal")
ROLLOVER_NOTE_LIMIT = 200
_CONTROL_FIELDS = ("paused", "changed_at", "note")
_RUN_FIELDS = ("started_at", "finished_at", "source", "outcome", "steps",
               "detail")


@dataclass(frozen=True, slots=True)
class RolloverControl:
    """The operator's pause of the automatic days.

    changed_at is None when no pause was ever set - the store holds no
    control file then.
    """

    paused: bool
    changed_at: str | None
    note: str


@dataclass(frozen=True, slots=True)
class RolloverRun:
    """One rollover: when, from where, what it moved, and how it ended."""

    started_at: str
    finished_at: str
    source: str
    outcome: str
    steps: tuple[str, ...]
    detail: str


def rollover_dir(store: Path) -> Path:
    return store / "rollover"


def rollover_lock_path(store: Path) -> Path:
    """The lock that the timer's rollover and the console's hold."""
    return rollover_dir(store) / ".lock"


def _control_path(store: Path) -> Path:
    return rollover_dir(store) / "control.json"


def _runs_dir(store: Path) -> Path:
    return rollover_dir(store) / "runs"


def check_rollover_note(value: object, where: str) -> None:
    """A pause note: printable text, ROLLOVER_NOTE_LIMIT characters at
    most. An empty note is legal."""
    if not isinstance(value, str) or len(value) > ROLLOVER_NOTE_LIMIT \
            or not value.isprintable():
        raise StoreError(f"{where}: expected printable text of at most "
                         f"{ROLLOVER_NOTE_LIMIT} characters")


def read_rollover_control(store: Path) -> RolloverControl:
    """The pause. With no control file, automatic days are not paused."""
    import json

    path = _control_path(store)
    if not path.is_file():
        return RolloverControl(paused=False, changed_at=None, note="")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"{path}: cannot read: {error}") from error
    if not isinstance(raw, dict) or set(raw) != set(_CONTROL_FIELDS):
        raise StoreError(f"{path}: expected the fields "
                         f"{sorted(_CONTROL_FIELDS)}")
    if not isinstance(raw["paused"], bool):
        raise StoreError(f"{path}.paused: expected true or false")
    if not isinstance(raw["changed_at"], str) or not raw["changed_at"]:
        raise StoreError(f"{path}.changed_at: expected a non-empty string")
    check_rollover_note(raw["note"], f"{path}.note")
    return RolloverControl(paused=raw["paused"],
                           changed_at=raw["changed_at"], note=raw["note"])


def write_rollover_control(store: Path, control: RolloverControl) -> None:
    """Replace the pause as one unit, last writer wins."""
    if not isinstance(control.paused, bool):
        raise StoreError("paused: expected true or false")
    if not control.changed_at:
        raise StoreError("changed_at: expected a non-empty string")
    check_rollover_note(control.note, "note")
    ensure_store(store)
    _replace_json(_control_path(store), {
        "paused": control.paused, "changed_at": control.changed_at,
        "note": control.note})


def _check_run(run: RolloverRun) -> None:
    if run.source not in ROLLOVER_SOURCES:
        raise StoreError(f"source: expected one of {ROLLOVER_SOURCES}")
    if run.outcome not in ROLLOVER_OUTCOMES:
        raise StoreError(f"outcome: expected one of {ROLLOVER_OUTCOMES}")
    if not all(step in ROLLOVER_STEPS for step in run.steps):
        raise StoreError(f"steps: expected steps from {ROLLOVER_STEPS}")
    if not run.started_at or not run.finished_at:
        raise StoreError("a rollover run needs its two timestamps")
    if not isinstance(run.detail, str):
        raise StoreError("detail: expected a string")


def write_rollover_run(store: Path, run: RolloverRun) -> None:
    """Store one run record - one write.

    The file name starts with the start instant in a fixed-width UTC
    shape, thus the names sort in time sequence. A random suffix keeps
    two runs of one microsecond apart.
    """
    import datetime
    import secrets

    _check_run(run)
    moment = datetime.datetime.fromisoformat(run.started_at)
    if moment.tzinfo is None:
        raise StoreError("started_at: expected a timestamp with a zone")
    stamp = moment.astimezone(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    ensure_store(store)
    write_once_json(_runs_dir(store) / f"{stamp}-{secrets.token_hex(4)}.json",
                    {"started_at": run.started_at,
                     "finished_at": run.finished_at, "source": run.source,
                     "outcome": run.outcome, "steps": list(run.steps),
                     "detail": run.detail})


def _read_run(path: Path) -> RolloverRun:
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"{path}: cannot read: {error}") from error
    if not isinstance(raw, dict) or set(raw) != set(_RUN_FIELDS) \
            or not isinstance(raw["steps"], list):
        raise StoreError(f"{path}: expected the fields {sorted(_RUN_FIELDS)}")
    run = RolloverRun(started_at=raw["started_at"],
                      finished_at=raw["finished_at"], source=raw["source"],
                      outcome=raw["outcome"], steps=tuple(raw["steps"]),
                      detail=raw["detail"])
    _check_run(run)
    return run


def list_rollover_runs(store: Path, limit: int) -> tuple[RolloverRun, ...]:
    """The newest run records, newest first, limit of them at most."""
    base = _runs_dir(store)
    if not base.is_dir():
        return ()
    names = sorted((entry.name for entry in base.iterdir()
                    if entry.is_file() and entry.name.endswith(".json")),
                   reverse=True)
    return tuple(_read_run(base / name) for name in names[:limit])
