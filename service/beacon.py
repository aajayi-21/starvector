"""The beacon sources and the fetch of one pulse (spec VP1 sections 3.4, 5).

The shell side of the pick after the close: the HTTP reads of the drand
relays, a fake source for the tests and the development box, and the
wait for a pulse that is not published. The checks of an answer are
pure and live in `pulse.py`.

There is no local fallback. A close that cannot get its pulse raises,
and the day stays in "closing" until a subsequent close gets it. A
local seed after an outage is a pick that the operator controls.
"""

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from service.pulse import (DRAND_QUICKNET, FAKE_CHAIN, BeaconChain, Pulse,
                           PulseError, checked_pulse, pulse_time)

BEACON_KINDS = ("drand", "fake")
DRAND_RELAYS = ("https://api.drand.sh", "https://drand.cloudflare.com")

# A plain client name: the Cloudflare relays refuse the default name of
# urllib with HTTP 403 (seen 2026-11-14).
_USER_AGENT = "starvector-beacon/1"

# The longest pause between two attempts while a pulse is late.
_BACKOFF_CAP_SECONDS = 30.0


class BeaconUnavailable(RuntimeError):
    """A source has not published the pulse, or did not answer."""


class BeaconError(RuntimeError):
    """The pulse did not come before the deadline, or did not check."""


@dataclass(frozen=True, slots=True)
class BeaconConfig:
    """The beacon part of the server config (spec VP1 rulings D1, D2).

    margin_seconds puts the pulse after the scheduled close. grace and
    retry are the waits of section 5: the close tries until the pulse
    time plus grace plus retry, then raises.
    """

    kind: str
    relays: tuple[str, ...]
    margin_seconds: int = 60
    grace_seconds: int = 30
    retry_seconds: int = 600

    @property
    def chain(self) -> BeaconChain:
        return DRAND_QUICKNET if self.kind == "drand" else FAKE_CHAIN


class BeaconSource(Protocol):
    """One answer for each source, for one pulse number."""

    chain: BeaconChain

    def answers(self, number: int) -> list[dict]:
        """The answers of the sources, or BeaconUnavailable."""
        ...

    def ready_at(self, number: int) -> int:
        """The Unix time at which the source can answer this pulse."""
        ...


@dataclass(frozen=True, slots=True)
class DrandRelays:
    """The drand HTTP relays, with one read from each of them."""

    relays: tuple[str, ...]
    chain: BeaconChain = DRAND_QUICKNET
    timeout_seconds: float = 10.0

    def ready_at(self, number: int) -> int:
        return pulse_time(number, self.chain)

    def answers(self, number: int) -> list[dict]:
        found = []
        for relay in self.relays:
            address = f"{relay}/{self.chain.chain_hash}/public/{number}"
            request = urllib.request.Request(
                address, headers={"User-Agent": _USER_AGENT})
            try:
                with urllib.request.urlopen(
                        request, timeout=self.timeout_seconds) as reply:
                    raw = json.loads(reply.read())
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise BeaconUnavailable(f"{address}: {error}") from error
            except json.JSONDecodeError as error:
                raise PulseError(f"{address}: not JSON: {error}") from error
            if not isinstance(raw, dict):
                raise PulseError(f"{address}: expected a JSON object")
            found.append(raw)
        return found


def fake_signature(number: int) -> str:
    """The signature that the fake source gives for one pulse."""
    return hashlib.sha256(f"fake-beacon:{number}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class FakeBeacon:
    """A source that answers each pulse with no wait, with two equal answers.

    It is for the tests and the development box. Its chain name is
    "fake", which the day record holds, so a fake pick does not go
    as a public one.
    """

    chain: BeaconChain = FAKE_CHAIN

    def ready_at(self, number: int) -> int:
        # Each fake pulse is there with no wait, so a test or a development box
        # can close a day before its scheduled close.
        return 0

    def answers(self, number: int) -> list[dict]:
        signature = fake_signature(number)
        randomness = hashlib.sha256(bytes.fromhex(signature)).hexdigest()
        answer = {"round": number, "signature": signature,
                  "randomness": randomness}
        return [answer, dict(answer)]


def make_source(config: BeaconConfig) -> BeaconSource:
    """The source that the config names."""
    match config.kind:
        case "drand":
            return DrandRelays(relays=config.relays)
        case "fake":
            return FakeBeacon()
        case _:
            raise BeaconError(f"unknown beacon kind: {config.kind!r}")


def fetch_pulse(source: BeaconSource, number: int, config: BeaconConfig, *,
                now: Callable[[], float] = time.time,
                sleep: Callable[[float], None] = time.sleep) -> Pulse:
    """The checked pulse, with the waits of spec VP1 section 5.

    The close tries with no wait, and while the sources say the pulse is not
    there, it tries again with a growing pause until the pulse time
    plus the grace plus the retry window. An answer that does not
    check raises with no wait: a wait does not repair it.
    """
    deadline = pulse_time(number, source.chain) + config.grace_seconds \
        + config.retry_seconds
    pause = 1.0
    while True:
        try:
            return checked_pulse(source.answers(number), number)
        except BeaconUnavailable as error:
            left = deadline - now()
            if left <= 0:
                raise BeaconError(
                    f"pulse {number} of {source.chain.name} did not arrive "
                    f"before the deadline: {error}") from error
            sleep(min(pause, left))
            pause = min(pause * 2, _BACKOFF_CAP_SECONDS)
        except PulseError as error:
            raise BeaconError(
                f"pulse {number} of {source.chain.name} did not pass the "
                f"checks: {error}") from error


# The clock offset above which the rollover warns (spec VP1 section 4).
CLOCK_WARNING_SECONDS = 5.0


def offset_from_date(date_header: str, local: float) -> float:
    """The local clock minus the time in an HTTP Date header, in seconds.

    The header has a resolution of one second, which is sufficient to
    see an offset that matters against a margin of 60 seconds.
    """
    import email.utils

    stamp = email.utils.parsedate_to_datetime(date_header)
    return local - stamp.timestamp()


def clock_offset(relay: str = DRAND_RELAYS[0],
                 now: Callable[[], float] = time.time) -> float:
    """The offset of the local clock from the Date header of the relays.

    The send gate reads the server clock and the pulse reads the drand
    clock, so a server clock that is late lets a send land after the
    pulse (spec VP1 section 4). The read takes the middle of the
    time of the read as the local instant.
    """
    request = urllib.request.Request(
        f"{relay}/{DRAND_QUICKNET.chain_hash}/info",
        headers={"User-Agent": _USER_AGENT})
    before = now()
    with urllib.request.urlopen(request, timeout=10.0) as reply:
        date_header = reply.headers.get("Date")
    after = now()
    if date_header is None:
        raise BeaconUnavailable(f"{relay}: the answer has no Date header")
    return offset_from_date(date_header, (before + after) / 2)


def parse_beacon_config(raw: object, source: str) -> BeaconConfig:
    """Check the beacon part of a server config file."""
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: expected an object")
    known = {"kind", "relays", "margin_seconds", "grace_seconds",
             "retry_seconds"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ValueError(f"{source}: unknown field(s): {', '.join(unknown)}")
    kind = raw.get("kind")
    if kind not in BEACON_KINDS:
        raise ValueError(f"{source}.kind: expected one of {list(BEACON_KINDS)}")
    relays: Sequence[object] = raw.get(
        "relays", DRAND_RELAYS if kind == "drand" else ())
    if not isinstance(relays, (list, tuple)) or not all(
            isinstance(relay, str) and relay.startswith("https://")
            for relay in relays):
        raise ValueError(f"{source}.relays: expected https addresses")
    if kind == "drand" and len(relays) < 2:
        raise ValueError(
            f"{source}.relays: drand needs two relays that must agree")
    values = {}
    for name, default in (("margin_seconds", 60), ("grace_seconds", 30),
                          ("retry_seconds", 600)):
        value = raw.get(name, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{source}.{name}: expected an integer from 0")
        values[name] = value
    return BeaconConfig(kind=kind, relays=tuple(relays), **values)


def main(argv: list[str] | None = None) -> int:
    """Read one pulse from the two drand relays and check it.

    The argument is the pulse number. The live check of spec VP1
    section 11, with the command in section 15. It runs by hand, because the
    test suite refuses each network connection (CLAUDE.md section 7).
    """
    import sys

    numbers = [int(value) for value in (argv or sys.argv[1:])]
    if len(numbers) != 1:
        print("usage: python -m service.beacon <pulse number>")
        return 2
    pulse = checked_pulse(DrandRelays(relays=DRAND_RELAYS).answers(numbers[0]),
                          numbers[0])
    print(f"pulse {pulse.number}: the two relays agree, randomness "
          f"{pulse.randomness}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
