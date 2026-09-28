"""Sessions and device codes: how a device signs in (spec BR1 section 4).

This module composes the token functions and the store. The server's
handlers use it, and so does the operator's command line. It reads
no environment and no clock - each function takes the instant.

The rules:

- A session is one signed-in device. Its value is "<player>.<secret>"
  and the store keeps the secret's digest as the record's file name.
  A session lives SESSION_MAX_AGE from its start and ends earlier
  when it is deleted or the player is revoked.
- A device code signs one more device in for a player who holds a
  session. It lives DEVICE_CODE_SECONDS and works one time.
"""

import datetime
from pathlib import Path

from service import auth, store


class AccessError(ValueError):
    """A sign-in move the rules refuse, with the refusal named."""


def _iso(instant: datetime.datetime) -> str:
    return instant.astimezone(datetime.UTC).isoformat()


def _parse(stamp: str) -> datetime.datetime:
    moment = datetime.datetime.fromisoformat(stamp)
    if moment.tzinfo is None:
        raise store.StoreError(f"a stored timestamp has no zone: {stamp!r}")
    return moment


def session_ends_at(record: store.SessionRecord) -> datetime.datetime:
    """The instant the session's fixed life ends."""
    return _parse(record.created_at) \
        + datetime.timedelta(seconds=auth.SESSION_MAX_AGE)


def session_expired(record: store.SessionRecord,
                    instant: datetime.datetime) -> bool:
    """The session's fixed life ends at or before this instant."""
    return instant >= session_ends_at(record)


def code_expired(record: store.DeviceCodeRecord,
                 instant: datetime.datetime) -> bool:
    """The device code's life ends at or before this instant."""
    return instant >= _parse(record.expires_at)


def open_session(root: Path, player: str, *, user_agent: object,
                 instant: datetime.datetime,
                 secret: str | None = None) -> str:
    """Store one new session for an active player, and answer its value.

    Refuses a player with no record or a revoked one: a session is a
    grant of the player's access, and a revoked player has none.
    """
    record = store.read_player_or_none(root, player)
    if record is None or record.status != "active":
        raise AccessError(f"player {player!r} is not an active player")
    value, digest = auth.mint_session(player, secret=secret)
    store.write_session_record(root, digest, store.SessionRecord(
        player=player, label=auth.device_label(user_agent),
        created_at=_iso(instant)))
    return value


def session_key(value: object) -> tuple[str, str] | None:
    """The (player, digest) a cookie value names, or None for other text."""
    parsed = auth.parse_token(value)
    if parsed is None:
        return None
    player, secret = parsed
    return player, auth.token_hash(secret)


def resolve_session(root: Path, value: object,
                    instant: datetime.datetime) -> str | None:
    """The player a cookie value signs in, or None.

    None covers each refusal alike: a value that does not parse, no
    session by that digest, a session at the end of its life, and a
    player with no record or a revoked one.
    """
    key = session_key(value)
    if key is None:
        return None
    player, digest = key
    record = store.read_session_or_none(root, player, digest)
    if record is None or session_expired(record, instant):
        return None
    owner = store.read_player_or_none(root, player)
    if owner is None or owner.status != "active":
        return None
    return player


def close_session(root: Path, value: object) -> bool:
    """Delete the session a cookie value names, and say if one was there."""
    key = session_key(value)
    if key is None:
        return False
    player, digest = key
    return store.delete_session(root, player, digest)


def session_rows(root: Path, player: str, current_digest: str | None,
                 instant: datetime.datetime) -> list[dict]:
    """The player's live sessions for the account screen, oldest first.

    Each row names the device, its start, and if it is the device that
    asks. The digest is the row's handle for a sign-out: it is a
    digest that goes in one direction, and a cookie cannot come from it.
    """
    rows = []
    for digest, record in store.list_sessions(root, player):
        if session_expired(record, instant):
            continue
        rows.append({"id": digest, "label": record.label,
                     "created_at": record.created_at,
                     "current": digest == current_digest})
    return rows


def issue_device_code(root: Path, player: str, instant: datetime.datetime,
                      code: str | None = None) -> tuple[str, str]:
    """Store one device code for the player, and answer it and its expiry.

    code arrives as an argument for the tests that pin one.
    """
    chosen = code or auth.make_device_code()
    if auth.normalize_device_code(chosen) != chosen:
        raise AccessError("a device code must be eight alphabet characters")
    expires = instant + datetime.timedelta(seconds=auth.DEVICE_CODE_SECONDS)
    store.write_device_code(root, auth.device_code_hash(chosen),
                            store.DeviceCodeRecord(
                                player=player, created_at=_iso(instant),
                                expires_at=_iso(expires)))
    return chosen, _iso(expires)


def redeem_device_code(root: Path, text: object,
                       instant: datetime.datetime) -> str | None:
    """The player a typed code signs in, or None.

    The claim removes the code in each outcome, thus an expired code
    also leaves the store at its first use. None covers text that is
    not a code, a code that is not stored or is used, a code at the
    end of its life, and a player who is no longer active.
    """
    code = auth.normalize_device_code(text)
    if code is None:
        return None
    record = store.claim_device_code(root, auth.device_code_hash(code))
    if record is None or code_expired(record, instant):
        return None
    owner = store.read_player_or_none(root, record.player)
    if owner is None or owner.status != "active":
        return None
    return record.player


def prune(root: Path, instant: datetime.datetime) -> dict[str, int]:
    """Remove each session at the end of its life and each expired device
    code."""
    counts = {"sessions": 0, "device_codes": 0}
    for player in _session_players(root):
        for digest, record in store.list_sessions(root, player):
            if session_expired(record, instant) \
                    and store.delete_session(root, player, digest):
                counts["sessions"] += 1
    for digest, record in store.list_device_codes(root):
        if code_expired(record, instant) \
                and store.remove_device_code(root, digest):
            counts["device_codes"] += 1
    return counts


def _session_players(root: Path) -> tuple[str, ...]:
    base = root / "sessions"
    if not base.is_dir():
        return ()
    names = []
    for entry in base.iterdir():
        try:
            store.check_player_name(entry.name, "player")
        except store.StoreError:
            continue
        if entry.is_dir():
            names.append(entry.name)
    return tuple(sorted(names))
