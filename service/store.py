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

from core.canonical import JsonValue, canonical_json_pretty, sha256_hex
from pool.artifacts import write_bytes_atomic, write_json_pretty

DAY_STATUSES = ("open", "closed", "revealed")
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
    the board label, and two players can hold equal labels. The
    store keeps token_hash, the digest of the invite secret. The
    store does not keep the secret, which the mint answers one time.
    """

    player: str
    display_name: str
    token_hash: str
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
    if not _TOKEN_HASH_RULE.fullmatch(record.token_hash):
        raise StoreError(
            f"token_hash: expected 64 lowercase hex characters, "
            f"got {record.token_hash!r}")
    if not record.created_at:
        raise StoreError("created_at: expected a non-empty string")


def write_player_record(store: Path, record: PlayerRecord) -> None:
    """Write a new player record - the mint alone does this, one time.

    The mint rides the one-write primitive. A second mint for the
    name thus raises, and an invite cannot silently change the
    credential that a name which plays today holds. The guarded
    edit below turns the token.
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
    if not _TOKEN_HASH_RULE.fullmatch(raw["token_hash"]):
        raise StoreError(
            f"{path}.token_hash: expected 64 lowercase hex characters")
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


def replace_player_token(store: Path, player: str, *, expect_status: str,
                         new_token_hash: str) -> PlayerRecord:
    """A guarded player-record edit: the stored invite digest moves.

    Reads the stored record again, refuses if its status is not
    expect_status, then writes the moved record. The name and the
    creation time do not move. The earlier invite stops at the read
    which follows, and so does each cookie that holds it.
    """
    if expect_status not in PLAYER_STATUSES:
        raise StoreError(f"unknown status: {expect_status!r}")
    if not _TOKEN_HASH_RULE.fullmatch(new_token_hash):
        raise StoreError(
            "new_token_hash: expected 64 lowercase hex characters")
    record = read_player_record(store, player)
    if record.status != expect_status:
        raise StoreError(
            f"player {player} has status {record.status!r} and the move "
            f"needs {expect_status!r}")
    moved = replace(record, token_hash=new_token_hash)
    write_json_pretty(player_record_path(store, player),
                      _player_to_value(moved))
    return moved


def set_player_status(store: Path, player: str, *, expect_status: str,
                      new_status: str) -> PlayerRecord:
    """The second guarded player edit: the status move.

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
    write_json_pretty(player_record_path(store, player),
                      _player_to_value(moved))
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


def write_account_record(store: Path, record: AccountRecord) -> None:
    """Write one account record, replacing the earlier one.

    The document lands in a temporary sibling and os.replace takes
    the destination - atomic, thus a torn document cannot occur.
    This is the account record's one edit path (spec A1 section 3).
    """
    _check_account_record(record)
    write_json_pretty(account_record_path(store, record.player),
                      _account_to_value(record))


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
    write_bytes_atomic(avatar_path(store, player), data)
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
