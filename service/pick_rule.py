"""The pick rule and the check of a vp1 day (spec VP1 sections 3.3, 3.5).

Pure functions with the standard library and the two pure modules of
spec VP1, so a reader of the public database can run the same check as
the server: tools/check_day.py imports this module.
"""

import hashlib
from collections.abc import Sequence

from service.pool_root import proof_agrees
from service.pulse import randomness_of


def pick_index(count: int, day: str, pick_seed: str) -> int:
    """The position of the day's target in the pool sequence (R6).

    The validation.v2 target rule with the day and the seed in the
    digest. The modulo bias is below N / 2**64 and is accepted, as
    there. In spec VP1 the seed is the randomness of the pulse.
    """
    digest = hashlib.sha256(f"day-target:{day}:{pick_seed}".encode())
    return int(digest.hexdigest()[:16], 16) % count


def vp1_faults(*, day: str, target_id: str, signature: str, randomness: str,
               target_index: int, target_salt: str,
               target_proof: Sequence[str], pool_count: int,
               pool_root: str) -> list[str]:
    """The faults of one vp1 day: checks 2 to 4 of spec VP1 section 3.5.

    An empty answer means the randomness is the digest of the signature,
    the position follows from the randomness, and the target with its
    salt and proof gives the committed pool root. Check 1, the BLS
    signature, and check 5, the times, use the beacon key and the
    repository history.
    """
    faults = []
    try:
        if randomness_of(signature) != randomness:
            faults.append(f"day {day}: the randomness is not the digest of "
                          "the signature")
    except ValueError:
        faults.append(f"day {day}: the signature is not hex")
    if pick_index(pool_count, day, randomness) != target_index:
        faults.append(f"day {day}: the position does not follow from the "
                      "randomness")
    if not proof_agrees(target_id, target_salt, target_index, pool_count,
                        target_proof, pool_root):
        faults.append(f"day {day}: the proof does not give the pool root")
    return faults


def instant_commitment(trial_id: str, nonce: str) -> str:
    """The commitment to the nonce of one instant trial (spec IM1 5.2).

    The receipt of the send holds it, and the result gives the nonce.
    """
    text = f"instant-nonce:{trial_id}:{nonce}"
    return hashlib.sha256(text.encode()).hexdigest()


def instant_index(count: int, trial_id: str, send_digest: str, nonce: str,
                  randomness: str) -> int:
    """The position of the target of one instant trial (spec IM1 5.2).

    count is the pool count N. The digest holds the trial, the digest
    of the stored send, the nonce of the server, and the randomness of
    the pulse. The modulo bias is below N / 2**64 and is accepted, as
    it is for pick_index.
    """
    text = f"instant-target:{trial_id}:{send_digest}:{nonce}:{randomness}"
    digest = hashlib.sha256(text.encode())
    return int(digest.hexdigest()[:16], 16) % count


def instant_faults(*, trial_id: str, send_digest: str, commitment: str,
                   nonce: str, signature: str, randomness: str,
                   target_id: str, target_index: int, target_salt: str,
                   target_proof: Sequence[str], pool_count: int,
                   pool_root: str) -> list[str]:
    """The faults of the pick of one instant trial (spec IM1 5.2).

    An empty answer means four things. The nonce agrees with the
    commitment of the receipt. The randomness is the digest of the
    signature. The position follows from the trial, the send, the
    nonce, and the randomness. The target with its salt and proof gives
    the committed pool root. The BLS signature and the times are
    checks of the reader, as they are for a day.
    """
    faults = []
    if instant_commitment(trial_id, nonce) != commitment:
        faults.append(f"trial {trial_id}: the nonce does not agree with "
                      "the commitment")
    try:
        if randomness_of(signature) != randomness:
            faults.append(f"trial {trial_id}: the randomness is not the "
                          "digest of the signature")
    except ValueError:
        faults.append(f"trial {trial_id}: the signature is not hex")
    position = instant_index(pool_count, trial_id, send_digest, nonce,
                             randomness)
    if position != target_index:
        faults.append(f"trial {trial_id}: the position does not follow "
                      "from the randomness")
    if not proof_agrees(target_id, target_salt, target_index, pool_count,
                        target_proof, pool_root):
        faults.append(f"trial {trial_id}: the proof does not give the "
                      "pool root")
    return faults
