"""The pure pieces of spec VP1: the pulse number and the pool root."""

import hashlib
import hmac

import pytest

from service import pool_root as pr
from service import pulse

CHAIN = pulse.DRAND_QUICKNET

# A pulse of drand quicknet, read from two relays on 2026-11-14.
LIVE_ROUND = 28832419
LIVE_SIGNATURE = ("acab0748f165c5f961538d5e4b400a989db7af6f389072dcfc230af10"
                  "ddddb3173213cd049bc39e2279b0bf9e15adb88")
LIVE_RANDOMNESS = ("00791107babeb0fb7dbb8fd2fcda6c34ac12655b3bb2fde8e229c1d8"
                   "4bc75a81")


def test_the_pulse_numbers_at_genesis_and_at_a_boundary() -> None:
    assert pulse.pulse_number(CHAIN.genesis, CHAIN) == 1
    assert pulse.pulse_number(CHAIN.genesis + 3, CHAIN) == 2
    assert pulse.pulse_number(CHAIN.genesis + 4, CHAIN) == 3
    assert pulse.pulse_time(2, CHAIN) == CHAIN.genesis + 3


def test_the_pulse_is_at_or_after_the_instant() -> None:
    for instant in range(CHAIN.genesis + 1, CHAIN.genesis + 40):
        number = pulse.pulse_number(instant, CHAIN)
        assert pulse.pulse_time(number, CHAIN) >= instant
        assert pulse.pulse_time(number - 1, CHAIN) < instant


def test_the_day_pulse_reads_the_scheduled_close_and_the_margin() -> None:
    closes_at = 1_794_700_800  # a midnight in UTC
    number = pulse.day_pulse_number(closes_at, 60, CHAIN)
    assert closes_at + 60 <= pulse.pulse_time(number, CHAIN) \
        < closes_at + 63


def test_the_live_pulse_passes_the_digest_check() -> None:
    assert pulse.randomness_of(LIVE_SIGNATURE) == LIVE_RANDOMNESS
    answer = {"round": LIVE_ROUND, "signature": LIVE_SIGNATURE,
              "randomness": LIVE_RANDOMNESS}
    checked = pulse.checked_pulse([answer, dict(answer)], LIVE_ROUND)
    assert checked.randomness == LIVE_RANDOMNESS


@pytest.mark.parametrize("change", [
    {"round": LIVE_ROUND + 1},
    {"randomness": "00" * 32},
    {"signature": "ab" * 48},
    {"signature": "XYZ"},
])
def test_a_bad_answer_raises(change) -> None:
    good = {"round": LIVE_ROUND, "signature": LIVE_SIGNATURE,
            "randomness": LIVE_RANDOMNESS}
    with pytest.raises(pulse.PulseError):
        pulse.checked_pulse([good, {**good, **change}], LIVE_ROUND)


def test_one_source_is_not_sufficient() -> None:
    good = {"round": LIVE_ROUND, "signature": LIVE_SIGNATURE,
            "randomness": LIVE_RANDOMNESS}
    with pytest.raises(pulse.PulseError):
        pulse.checked_pulse([good], LIVE_ROUND)


KEY = bytes(range(32))


def _ids(count: int) -> list[str]:
    return [f"img-{index:04d}" for index in range(count)]


def test_the_digests_agree_with_fixed_vectors() -> None:
    salt = pr.leaf_salt(KEY, "img-0000")
    assert salt == hmac.new(KEY, b"img-0000", "sha256").hexdigest()
    leaf = pr.leaf_digest(salt, "img-0000")
    assert leaf == hashlib.sha256(
        f"vp1-leaf:{salt}:img-0000".encode()).hexdigest()
    assert pr.pool_root(["img-0000"], KEY) == hashlib.sha256(
        f"vp1-root:1:{leaf}".encode()).hexdigest()


@pytest.mark.parametrize("count", [1, 2, 3, 4, 5, 7, 8, 13, 1000])
def test_each_position_proves_to_the_root(count) -> None:
    ids = _ids(count)
    root = pr.pool_root(ids, KEY)
    for index in sorted({0, count // 2, count - 1}):
        steps = pr.proof_of(ids, KEY, index)
        salt = pr.leaf_salt(KEY, ids[index])
        assert pr.proof_agrees(ids[index], salt, index, count, steps, root)


def test_a_changed_proof_fails() -> None:
    ids = _ids(13)
    root = pr.pool_root(ids, KEY)
    steps = list(pr.proof_of(ids, KEY, 6))
    salt = pr.leaf_salt(KEY, ids[6])
    side, _, digest = steps[0].partition(":")
    flipped = ("0" if digest[0] != "0" else "1") + digest[1:]
    bad = [f"{side}:{flipped}", *steps[1:]]
    assert not pr.proof_agrees(ids[6], salt, 6, 13, bad, root)
    assert not pr.proof_agrees(ids[6], salt, 7, 13, steps, root)
    assert not pr.proof_agrees(ids[5], salt, 6, 13, steps, root)
    assert not pr.proof_agrees(ids[6], "00" * 32, 6, 13, steps, root)
    assert not pr.proof_agrees(ids[6], salt, 6, 13, steps[:-1], root)
    assert not pr.proof_agrees(ids[6], salt, 6, 13, [*steps, steps[0]],
                               root)


def test_the_root_changes_when_the_set_changes() -> None:
    ids = _ids(10)
    assert pr.pool_root(ids, KEY) != pr.pool_root(ids[:-1], KEY)
    assert pr.pool_root(ids, KEY) != pr.pool_root(
        [*ids[:-1], "img-other"], KEY)
    assert pr.pool_root(ids, KEY) != pr.pool_root(ids, bytes(32))



def test_the_offset_reads_an_http_date() -> None:
    from service.beacon import offset_from_date

    header = "Mon, 16 Nov 2026 00:00:00 GMT"
    midnight = 1794787200.0
    assert offset_from_date(header, midnight) == 0.0
    assert offset_from_date(header, midnight + 7.5) == 7.5


def test_the_rollover_warns_on_a_clock_that_is_off() -> None:
    from service.beacon import BeaconUnavailable
    from service.rollover import clock_agrees

    lines: list[str] = []
    assert clock_agrees(say=lines.append, offset=lambda: 1.0)
    assert not clock_agrees(say=lines.append, offset=lambda: -9.0)
    assert "off by -9.0 s" in lines[-1]

    def unreachable() -> float:
        raise BeaconUnavailable("no answer")

    assert clock_agrees(say=lines.append, offset=unreachable)
    assert "did not read a relay" in lines[-1]
