"""The pure rules of an instant trial (spec IM1 sections 5, 6, 11, 20)."""

import hashlib

import pytest

from service import instant
from service.pick_rule import (instant_commitment, instant_faults,
                               instant_index)
from service.pool_root import leaf_salt, pool_root, proof_of
from service.pulse import DRAND_QUICKNET, pulse_time, randomness_of

TRIAL = "0123456789abcdef0123456789abcdef"
NONCE = "ab" * 32
SIGNATURE = "cd" * 48
POOL_KEY = bytes(range(32))
IMAGE_IDS = tuple(f"image-{number:03d}" for number in range(37))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_commitment_is_the_digest_of_the_trial_and_the_nonce() -> None:
    assert instant_commitment(TRIAL, NONCE) == _sha(
        f"instant-nonce:{TRIAL}:{NONCE}")


def test_the_position_is_the_digest_rule_of_the_spec() -> None:
    randomness = randomness_of(SIGNATURE)
    digest = _sha(f"instant-target:{TRIAL}:feed:{NONCE}:{randomness}")
    assert instant_index(37, TRIAL, "feed", NONCE, randomness) \
        == int(digest[:16], 16) % 37


def test_the_position_is_a_known_vector() -> None:
    # A pinned value: a change of the rule moves each stored target.
    assert instant_index(1393, TRIAL, "00" * 32, NONCE, "11" * 32) == 78


@pytest.mark.parametrize("field", ["trial_id", "send_digest", "nonce",
                                   "randomness"])
def test_each_input_moves_the_position(field: str) -> None:
    base = {"trial_id": TRIAL, "send_digest": "00" * 32, "nonce": NONCE,
            "randomness": "11" * 32}
    positions = set()
    for variant in range(40):
        changed = dict(base)
        changed[field] = _sha(f"{field}:{variant}")
        positions.add(instant_index(1_000_000, **changed))
    assert len(positions) == 40


def _picked_trial() -> dict:
    digest = instant.send_digest({"strokes": [], "impressions": ["a"]})
    randomness = randomness_of(SIGNATURE)
    index = instant_index(len(IMAGE_IDS), TRIAL, digest, NONCE, randomness)
    target_id = IMAGE_IDS[index]
    return {
        "trial_id": TRIAL, "send_digest": digest,
        "commitment": instant_commitment(TRIAL, NONCE), "nonce": NONCE,
        "signature": SIGNATURE, "randomness": randomness,
        "target_id": target_id, "target_index": index,
        "target_salt": leaf_salt(POOL_KEY, target_id),
        "target_proof": proof_of(IMAGE_IDS, POOL_KEY, index),
        "pool_count": len(IMAGE_IDS),
        "pool_root": pool_root(IMAGE_IDS, POOL_KEY),
    }


def test_a_correct_pick_has_no_fault() -> None:
    assert instant_faults(**_picked_trial()) == []


@pytest.mark.parametrize("field, value, words", [
    ("send_digest", "00" * 32, "position"),
    ("nonce", "ef" * 32, "commitment"),
    ("randomness", "22" * 32, "digest of the signature"),
    ("signature", "ab" * 48, "digest of the signature"),
    ("signature", "not hex", "not hex"),
    ("target_id", "image-000x", "pool root"),
    ("target_salt", "00" * 32, "pool root"),
    ("target_proof", (), "pool root"),
    ("pool_root", "00" * 32, "pool root"),
])
def test_a_changed_pick_has_a_fault(field: str, value: object,
                                    words: str) -> None:
    trial = _picked_trial()
    trial[field] = value
    assert any(words in fault for fault in instant_faults(**trial))


def test_a_changed_send_changes_the_digest() -> None:
    first = instant.send_digest({"impressions": ["a"], "strokes": []})
    same = instant.send_digest({"strokes": [], "impressions": ["a"]})
    other = instant.send_digest({"strokes": [], "impressions": ["b"]})
    assert first == same and first != other


@pytest.mark.parametrize("tenths", range(0, 31))
def test_the_pulse_time_is_after_the_send_time_plus_the_margin(
        tenths: int) -> None:
    # Send times at each tenth of a second of one period of the chain.
    seconds = 1_800_000_000 + tenths / 10
    stamp = _stamp(seconds)
    number = instant.send_pulse_number(stamp, instant.MARGIN_SECONDS,
                                       DRAND_QUICKNET)
    wait = pulse_time(number, DRAND_QUICKNET) - seconds
    assert instant.MARGIN_SECONDS <= wait
    assert wait < instant.MARGIN_SECONDS + DRAND_QUICKNET.period + 1


def _stamp(seconds: float) -> str:
    import datetime

    return datetime.datetime.fromtimestamp(
        seconds, datetime.UTC).isoformat()


def test_a_stamp_with_no_time_zone_is_refused() -> None:
    with pytest.raises(instant.InstantError):
        instant.unix_seconds("2026-11-23T10:00:00")
    with pytest.raises(instant.InstantError):
        instant.unix_seconds("yesterday")


def test_the_date_of_a_stamp_is_its_utc_date() -> None:
    assert instant.utc_date("2026-11-23T23:30:00-02:00") == "2026-11-24"
    assert instant.utc_date("2026-11-23T23:59:59+00:00") == "2026-11-23"


def _chain(count: int) -> list[instant.ChainRow]:
    rows = []
    previous = instant.CHAIN_START
    for position in range(count):
        fields = {"trial_id": f"{position:032x}",
                  "send_digest": _sha(f"send {position}"),
                  "commitment": _sha(f"nonce {position}"),
                  "received_at": _stamp(1_800_000_000 + position),
                  "beacon_round": 1000 + position}
        digest = instant.chain_digest(previous, **fields)
        rows.append(instant.ChainRow(position=position, previous=previous,
                                     digest=digest, **fields))
        previous = digest
    return rows


def test_a_correct_chain_has_no_fault() -> None:
    assert instant.chain_faults(_chain(6)) == []
    assert instant.chain_faults([]) == []


def test_the_chain_reads_the_rows_in_each_sequence() -> None:
    assert instant.chain_faults(list(reversed(_chain(6)))) == []


def test_a_removed_send_is_a_chain_fault() -> None:
    rows = _chain(6)
    del rows[2]
    assert instant.chain_faults(rows)


def test_a_changed_send_is_a_chain_fault() -> None:
    rows = _chain(6)
    rows[3] = rows[3]._replace(send_digest=_sha("a different send"))
    faults = instant.chain_faults(rows)
    assert any("send 3" in fault for fault in faults)


def test_an_added_send_is_a_chain_fault() -> None:
    rows = _chain(4)
    extra = rows[2]._replace(trial_id="f" * 32)
    assert instant.chain_faults(rows + [extra])


def test_the_first_send_follows_the_chain_start() -> None:
    rows = _chain(2)
    rows[0] = rows[0]._replace(previous="1" * 64)
    assert instant.chain_faults(rows)


@pytest.mark.parametrize("start, today, expired", [
    ("2026-11-23", "2026-11-23", False),
    ("2026-11-23", "2026-11-24", False),
    ("2026-11-23", "2026-11-25", True),
    ("2026-12-31", "2027-01-01", False),
    ("2026-12-31", "2027-01-02", True),
])
def test_a_start_is_good_on_its_date_and_the_date_after(
        start: str, today: str, expired: bool) -> None:
    assert instant.start_expired(start, today) is expired


def test_a_bad_date_is_refused() -> None:
    with pytest.raises(instant.InstantError):
        instant.start_expired("2026-11-23", "soon")


@pytest.mark.parametrize("sent, cap, left", [
    (0, 5, 5), (4, 5, 1), (5, 5, 0), (7, 5, 0), (0, 20, 20)])
def test_the_sends_that_an_owner_has_left(sent: int, cap: int,
                                          left: int) -> None:
    assert instant.sends_left(sent, cap) == left


def test_a_count_below_zero_is_refused() -> None:
    with pytest.raises(instant.InstantError):
        instant.sends_left(-1, 5)


@pytest.mark.parametrize("offset, refuses", [
    (None, True), (0.0, False), (3.0, False), (-3.0, False),
    (3.5, True), (-4.0, True)])
def test_the_clock_guard(offset: float | None, refuses: bool) -> None:
    assert instant.clock_refuses(
        offset, instant.CLOCK_BOUND_SECONDS) is refuses
