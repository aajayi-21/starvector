"""Guest play: the guest record, its cookie, and its claim.

Spec IM1 section 7. A guest is a visitor with no account. A cookie of
the browser is its identity, and the store keeps three types of file
in store/guests/<guest>/: the guest record, one consent record for
each notice version, and the claim that a sign-up writes. Each one is
a raw fact (rule I4) and is written one time.
"""

import datetime
import re
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path

from service import auth
from service.store import StoreError, read_json_or_none, write_once_json

GUEST_COOKIE = "sv_guest"

# The life of the guest cookie (spec IM1 decision D6): the life of a
# session cookie. The guest record has no end.
GUEST_MAX_AGE = auth.SESSION_MAX_AGE

# "guest-" and 16 hex characters: 22 characters. A username has no
# more than 20, thus a guest and an account do not have one name.
_GUEST_RULE = re.compile(r"guest-[0-9a-f]{16}")
_PLAYER_RULE = re.compile(r"[a-z0-9-]{1,64}")
_DIGEST_RULE = re.compile(r"[0-9a-f]{64}")

_GUEST_FIELDS = ("guest", "token_hash", "created_at")
_CONSENT_FIELDS = ("guest", "notice", "agreed_at")
_CLAIM_FIELDS = ("guest", "player", "claimed_at")


@dataclass(frozen=True, slots=True)
class GuestRecord:
    """One guest: its identifier and the digest of its cookie secret."""

    guest: str
    token_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    """The account that a guest became at a sign-up (spec IM1 7.4)."""

    guest: str
    player: str
    claimed_at: str


def is_guest_id(value: object) -> bool:
    return isinstance(value, str) and _GUEST_RULE.fullmatch(value) is not None


def make_guest_id() -> str:
    """A new guest identifier, from no datum of the visitor."""
    return "guest-" + secrets.token_hex(8)


def guests_dir(store: Path) -> Path:
    return store / "guests"


def guest_dir(store: Path, guest: str) -> Path:
    """The directory of one guest. The name becomes a file name, thus
    it must agree with its rule in full."""
    if not is_guest_id(guest):
        raise StoreError(f"not a guest identifier: {guest!r}")
    return guests_dir(store) / guest


def _stamp(instant: datetime.datetime) -> str:
    return instant.astimezone(datetime.UTC).isoformat()


def _checked(path: Path, names: tuple[str, ...], guest: str) -> dict | None:
    """The stored object of one guest file, or None with no file.

    A file with a different set of names, or with the identifier of a
    different guest, raises: it does not read as a record.
    """
    raw = read_json_or_none(path)
    if raw is None:
        return None
    if set(raw) != set(names) or raw.get("guest") != guest:
        raise StoreError(f"{path}: not a record of guest {guest}")
    return raw


def write_guest(store: Path, record: GuestRecord) -> None:
    """Write the record of one new guest, one time."""
    if not _DIGEST_RULE.fullmatch(record.token_hash) \
            or not record.created_at:
        raise StoreError(f"guest {record.guest}: not a guest record")
    write_once_json(guest_dir(store, record.guest) / "guest.json",
                    asdict(record))


def read_guest_or_none(store: Path, guest: str) -> GuestRecord | None:
    path = guest_dir(store, guest) / "guest.json"
    raw = _checked(path, _GUEST_FIELDS, guest)
    if raw is None:
        return None
    if not isinstance(raw["token_hash"], str) \
            or not _DIGEST_RULE.fullmatch(raw["token_hash"]) \
            or not isinstance(raw["created_at"], str):
        raise StoreError(f"{path}: not a guest record")
    return GuestRecord(**raw)


def consent_path(store: Path, guest: str, notice: int) -> Path:
    return guest_dir(store, guest) / "consents" / f"{notice}.json"


def write_consent(store: Path, guest: str, notice: int,
                  agreed_at: str) -> bool:
    """Record that a guest agreed to one notice version, one time.

    The answer says if this write made the record. A record that was
    there stays: the first agreement keeps its time.
    """
    if not isinstance(notice, int) or isinstance(notice, bool) or notice < 1:
        raise StoreError(f"notice: expected a version number, got {notice!r}")
    if not agreed_at:
        raise StoreError("agreed_at: expected a non-empty string")
    path = consent_path(store, guest, notice)
    try:
        write_once_json(path, {"guest": guest, "notice": notice,
                               "agreed_at": agreed_at})
    except StoreError:
        if path.is_file():
            return False
        raise
    return True


def agreed(store: Path, guest: str, notice: int) -> bool:
    """Tell if the guest agreed to this version of the notice.

    A stored record that does not validate raises: it does not read as
    an agreement.
    """
    path = consent_path(store, guest, notice)
    raw = _checked(path, _CONSENT_FIELDS, guest)
    if raw is None:
        return False
    if raw["notice"] != notice or not isinstance(raw["agreed_at"], str) \
            or not raw["agreed_at"]:
        raise StoreError(f"{path}: not the consent record of {guest} for "
                         f"notice {notice}")
    return True


def write_claim(store: Path, claim: ClaimRecord) -> None:
    """Write the claim of one guest, one time.

    A second claim of the guest raises: one guest becomes one account.
    """
    if not _PLAYER_RULE.fullmatch(claim.player) or not claim.claimed_at:
        raise StoreError(f"guest {claim.guest}: not a claim record")
    write_once_json(guest_dir(store, claim.guest) / "claim.json",
                    asdict(claim))


def read_claim_or_none(store: Path, guest: str) -> ClaimRecord | None:
    path = guest_dir(store, guest) / "claim.json"
    raw = _checked(path, _CLAIM_FIELDS, guest)
    if raw is None:
        return None
    if not isinstance(raw["player"], str) \
            or not _PLAYER_RULE.fullmatch(raw["player"]) \
            or not isinstance(raw["claimed_at"], str):
        raise StoreError(f"{path}: not a claim record")
    return ClaimRecord(**raw)


def claims_by_player(store: Path) -> dict[str, tuple[str, ...]]:
    """The claimed guests of each account, read from the store.

    The server keeps this map in memory as a cache of the claim
    records. One sign-up claims one guest, thus an account has one
    guest here. The value is a sequence, because the store rule and
    not this reader holds that count.
    """
    found: dict[str, list[str]] = {}
    root = guests_dir(store)
    if not root.is_dir():
        return {}
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not is_guest_id(entry.name):
            continue
        claim = read_claim_or_none(store, entry.name)
        if claim is not None:
            found.setdefault(claim.player, []).append(claim.guest)
    return {player: tuple(names) for player, names in found.items()}


def make_guest(store: Path, *, notice: int,
               instant: datetime.datetime) -> tuple[str, str]:
    """Make one guest with its agreement to the notice.

    The answer is the identifier and the cookie value. The store keeps
    the digest of the secret alone, as it does for a session.
    """
    guest = make_guest_id()
    value, digest = auth.mint_session(guest)
    stamp = _stamp(instant)
    write_guest(store, GuestRecord(guest=guest, token_hash=digest,
                                   created_at=stamp))
    write_consent(store, guest, notice, stamp)
    return guest, value


def resolve_guest(store: Path, value: object) -> str | None:
    """The guest behind a cookie value, or None.

    None answers text that is not a token, a name that is not a guest
    identifier, a guest with no record, a secret that does not agree,
    and a guest with a claim: the token of a claimed guest opens
    nothing (spec IM1 section 7.4). The digests are compared in
    constant time.
    """
    parsed = auth.parse_token(value)
    if parsed is None:
        return None
    guest, secret = parsed
    if not is_guest_id(guest):
        return None
    record = read_guest_or_none(store, guest)
    if record is None:
        return None
    if not secrets.compare_digest(auth.token_hash(secret),
                                  record.token_hash):
        return None
    if read_claim_or_none(store, guest) is not None:
        return None
    return guest


def claim_guest(store: Path, guest: str, player: str,
                instant: datetime.datetime) -> ClaimRecord:
    """Write the claim that makes the trials of a guest the trials of
    an account. No trial file changes (spec SC1 rule 3)."""
    claim = ClaimRecord(guest=guest, player=player,
                        claimed_at=_stamp(instant))
    write_claim(store, claim)
    return claim


def _cookie(value: str, max_age: int, secure: bool) -> str:
    parts = [f"{GUEST_COOKIE}={value}", "Path=/"]
    if secure:
        parts.append("Secure")
    parts.extend(["HttpOnly", "SameSite=Lax", f"Max-Age={max_age}"])
    return "; ".join(parts)


def guest_cookie_header(value: str, *, secure: bool = True) -> str:
    """The Set-Cookie value of one guest, with the attributes of the
    session cookie (spec IM1 section 7.1)."""
    return _cookie(value, GUEST_MAX_AGE, secure)


def clear_guest_cookie_header(*, secure: bool = True) -> str:
    """The Set-Cookie value that removes the guest cookie."""
    return _cookie("", 0, secure)
