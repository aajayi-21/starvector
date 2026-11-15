"""The beacon pulse that picks the target of a day (spec VP1 section 3.2).

Pure functions: the pulse number of an instant, the time of a pulse,
and the check of the answers of the beacon sources for one pulse. The
fetch is the shell's work (service/beacon.py). No clock and no network
here.
"""

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_HEX_RULE = re.compile(r"[0-9a-f]+")


class PulseError(ValueError):
    """An answer of a beacon source did not pass the checks."""


@dataclass(frozen=True, slots=True)
class BeaconChain:
    """The fixed facts of one beacon chain.

    genesis is the Unix time in seconds of pulse 1, and period is the
    seconds between pulses. The facts of drand quicknet were checked
    against its info document on 2026-11-14 (spec VP1 section 3.2).
    """

    name: str
    chain_hash: str
    genesis: int
    period: int
    public_key: str
    scheme: str


DRAND_QUICKNET = BeaconChain(
    name="drand-quicknet",
    chain_hash="52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971",
    genesis=1692803367,
    period=3,
    public_key=(
        "83cf0f2896adee7eb8b5f01fcad3912212c437e0073e911fb90022d3e760183c"
        "8c4b450b6a0a6c3ac6a5776a2d1064510d1fec758c921cc22b0e17e63aaf4bcb"
        "5ed66304de9cf809bd274ca73bab4af5a6e9c76a4bc09e76eae8991ef5ece45a"),
    scheme="bls-unchained-g1-rfc9380",
)

# The chain of the fake source of the tests and the development box.
# Its timing agrees with quicknet, so the pulse numbers look the same,
# and its name says it is not a public beacon.
FAKE_CHAIN = BeaconChain(
    name="fake",
    chain_hash="fake",
    genesis=DRAND_QUICKNET.genesis,
    period=DRAND_QUICKNET.period,
    public_key="",
    scheme="fake-sha256",
)


def chain_named(name: str) -> BeaconChain:
    """The chain a day record names, or PulseError."""
    for chain in (DRAND_QUICKNET, FAKE_CHAIN):
        if chain.name == name:
            return chain
    raise PulseError(f"unknown beacon chain: {name!r}")


@dataclass(frozen=True, slots=True)
class Pulse:
    """One checked pulse: its number, its signature, and its randomness.

    randomness is 64 lowercase hex characters: the SHA-256 digest of
    the signature bytes.
    """

    number: int
    signature: str
    randomness: str


def pulse_number(instant: int, chain: BeaconChain) -> int:
    """The first pulse with a time at or after instant (Unix seconds)."""
    if instant <= chain.genesis:
        return 1
    return math.ceil((instant - chain.genesis) / chain.period) + 1


def pulse_time(number: int, chain: BeaconChain) -> int:
    """The Unix time in seconds of one pulse."""
    if number < 1:
        raise PulseError(f"a pulse number starts at 1, got {number}")
    return chain.genesis + (number - 1) * chain.period


def day_pulse_number(closes_at: int, margin: int, chain: BeaconChain) -> int:
    """The pulse that picks the target of a day (spec VP1 section 3.2).

    It comes from the scheduled close instant and the margin alone.
    The moment that the timer closes the day does not move it, so an
    operator who delays the close does not get a different pulse.
    """
    return pulse_number(closes_at + margin, chain)


def randomness_of(signature: str) -> str:
    """The randomness of a pulse: the SHA-256 digest of the signature."""
    return hashlib.sha256(bytes.fromhex(signature)).hexdigest()


def _checked_answer(answer: Mapping[str, object], number: int,
                    where: str) -> Pulse:
    found = answer.get("round")
    if not isinstance(found, int) or isinstance(found, bool) \
            or found != number:
        raise PulseError(f"{where}: expected pulse {number}, got {found!r}")
    signature = answer.get("signature")
    randomness = answer.get("randomness")
    for name, value in (("signature", signature),
                        ("randomness", randomness)):
        if not isinstance(value, str) or not value \
                or len(value) % 2 or not _HEX_RULE.fullmatch(value):
            raise PulseError(f"{where}.{name}: expected lowercase hex")
    assert isinstance(signature, str) and isinstance(randomness, str)
    if randomness_of(signature) != randomness:
        raise PulseError(
            f"{where}: the randomness is not the SHA-256 digest of the "
            "signature")
    return Pulse(number=number, signature=signature, randomness=randomness)


def checked_pulse(answers: Sequence[Mapping[str, object]],
                  number: int) -> Pulse:
    """One pulse from the answers of the sources, or PulseError.

    Each answer must name the pulse, hold hex values, and have a
    randomness equal to the digest of its signature. The answers must
    agree on the signature (spec VP1 section 3.4). The check of the
    BLS signature against the chain key is ruling D3's later step.
    """
    if len(answers) < 2:
        raise PulseError(
            f"expected the answers of two sources, got {len(answers)}")
    pulses = [_checked_answer(answer, number, f"source {index}")
              for index, answer in enumerate(answers)]
    if len({pulse.signature for pulse in pulses}) != 1:
        raise PulseError(
            f"the sources disagree on the signature of pulse {number}")
    return pulses[0]
