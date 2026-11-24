"""The pure rules of an instant trial (spec IM1 sections 5, 6, and 11).

Pure functions: the owner of a trial, the digest of a send, the pulse
of a send, the chain of the sends, the dates of a start, and the count
of sends that an owner has. No clock, no network, and no file here. The
pick rule is in pick_rule.py.
"""

import datetime
import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from core.canonical import JsonValue, canonical_json, sha256_hex
from service.pulse import BeaconChain, pulse_number

# The two types of owner (spec IM1 section 4).
ACCOUNT = "account"
GUEST = "guest"
OWNER_KINDS = (ACCOUNT, GUEST)

# The margin between the time of a send and the time of its pulse, in
# seconds (spec IM1 section 22, D1): one period of drand quicknet.
MARGIN_SECONDS = 3

# The bound of the clock guard, in seconds (D2): the margin. The Date
# header of a beacon source has a resolution of one second, thus a
# smaller bound fires on measurement noise.
CLOCK_BOUND_SECONDS = float(MARGIN_SECONDS)

# The chain value before the first send (spec IM1 section 11).
CHAIN_START = "0" * 64


class InstantError(ValueError):
    """A value of an instant trial did not agree with its rule."""


@dataclass(frozen=True, slots=True)
class Owner:
    """The account or the guest that made an instant trial.

    The first field is one of OWNER_KINDS. The second field is the
    player name of an account or the identifier of a guest. Scoring
    code does not read an owner.
    """

    kind: str
    key: str


def send_digest(record: JsonValue) -> str:
    """The SHA-256 digest of the canonical JSON of one wire record."""
    return sha256_hex(canonical_json(record))


def unix_seconds(stamp: str) -> float:
    """The Unix time of one stored ISO stamp, or InstantError.

    A stamp with no time zone is refused: the server writes UTC stamps,
    and a stamp of a local clock gives a different pulse.
    """
    try:
        instant = datetime.datetime.fromisoformat(stamp)
    except (TypeError, ValueError) as error:
        raise InstantError(f"not an ISO stamp: {stamp!r}") from error
    if instant.tzinfo is None:
        raise InstantError(f"the stamp has no time zone: {stamp!r}")
    return instant.timestamp()


def utc_date(stamp: str) -> str:
    """The UTC date of one stored ISO stamp, as YYYY-MM-DD."""
    seconds = unix_seconds(stamp)
    instant = datetime.datetime.fromtimestamp(seconds, datetime.UTC)
    return instant.date().isoformat()


def send_pulse_number(received_at: str, margin: int,
                      chain: BeaconChain) -> int:
    """The pulse that picks the target of one send (spec IM1 5.3).

    The first pulse with a time at or after the time of the send plus
    the margin. It comes from the stored time and the margin alone.
    """
    instant = math.ceil(unix_seconds(received_at)) + margin
    return pulse_number(instant, chain)


def chain_digest(previous: str, *, trial_id: str, send_digest: str,
                 commitment: str, received_at: str,
                 beacon_round: int) -> str:
    """The chain value of one send (spec IM1 section 11).

    previous is the chain value of the send before this one, or
    CHAIN_START for the first send.
    """
    text = (f"instant-chain:{previous}:{trial_id}:{send_digest}:"
            f"{commitment}:{received_at}:{beacon_round}")
    return hashlib.sha256(text.encode()).hexdigest()


class ChainRow(NamedTuple):
    """The chain fields of one stored send."""

    position: int
    previous: str
    digest: str
    trial_id: str
    send_digest: str
    commitment: str
    received_at: str
    beacon_round: int


def chain_faults(rows: Sequence[ChainRow]) -> list[str]:
    """The faults of a chain of sends, read from position 0.

    An empty answer means that the positions count from 0 with no
    hole, each row names the chain value of the row before it, and
    each chain value is the digest of its row. A removed send, an
    added send, and a changed send each give a fault.
    """
    faults = []
    previous = CHAIN_START
    for expected, row in enumerate(sorted(rows)):
        where = f"send {row.position} (trial {row.trial_id})"
        if row.position != expected:
            faults.append(f"{where}: expected position {expected}")
        if row.previous != previous:
            faults.append(f"{where}: does not follow the send before it")
        digest = chain_digest(
            row.previous, trial_id=row.trial_id,
            send_digest=row.send_digest, commitment=row.commitment,
            received_at=row.received_at, beacon_round=row.beacon_round)
        if digest != row.digest:
            faults.append(f"{where}: the chain value is not the digest "
                          "of the row")
        previous = row.digest
    return faults


def start_expired(start_date: str, today: str) -> bool:
    """Tell if a start is too far back for a send (spec IM1 12.2).

    A start is good on its own UTC date and on the date after it. The
    two arguments are dates as YYYY-MM-DD.
    """
    try:
        started = datetime.date.fromisoformat(start_date)
        current = datetime.date.fromisoformat(today)
    except (TypeError, ValueError) as error:
        raise InstantError(
            f"not a date: {start_date!r} or {today!r}") from error
    return current > started + datetime.timedelta(days=1)


def sends_left(sent_today: int, day_cap: int) -> int:
    """The sends that an owner has left on one UTC date.

    sent_today counts each stored send of the date, with or without a
    result. day_cap is the cap of the owner type (spec IM1 section 6).
    """
    if sent_today < 0 or day_cap < 0:
        raise InstantError("a count of sends is not below zero")
    return max(0, day_cap - sent_today)


def clock_refuses(offset_seconds: float | None, bound: float) -> bool:
    """Tell if the clock guard refuses a send (spec IM1 5.3).

    offset_seconds is the last measured difference between the server
    clock and a beacon source, or None with no measurement. With no
    measurement the guard refuses: a clock that nobody measured is not
    a clock that the public times can use.
    """
    return offset_seconds is None or abs(offset_seconds) > bound
