"""The proof of work at sign-up (spec PW1).

A sign-up holds an ALTCHA payload: the browser found the counter of a
challenge that this server signed. The work is small for one person
and large for a script that makes many accounts. It is not a test of
a person, and the caps of spec A2 decision D11 stay.

The challenge key is a deployment secret. It arrives as an argument
here, and the start-up path reads it from the environment.
"""

import binascii
import datetime
import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass

import altcha

# Decision D2 of spec PW1: the default algorithm of the widget, which
# the browser computes with its own cryptography.
ALGORITHM = "PBKDF2/SHA-256"

# Decision D3: the values of the example of the ALTCHA library.
DEPLOYED_COST = 5_000
DEPLOYED_COUNTER_LOW = 5_000
DEPLOYED_COUNTER_HIGH = 10_000

# Decision D4: the life of one challenge.
LIFETIME_SECONDS = 10 * 60

# Decision D6: the environment name of the challenge key.
KEY_ENVIRONMENT_NAME = "STARVECTOR_ALTCHA_KEY"

# Decision D10: a payload of this server is less than 1,000
# characters. A longer text gets no parse.
PAYLOAD_MAX_CHARS = 4_096

# The labels of the two subkeys. After a change, each open challenge
# does not agree one time, and nothing more.
_CHALLENGE_LABEL = b"starvector altcha challenge signature"
_DERIVED_LABEL = b"starvector altcha derived key signature"


@dataclass(frozen=True)
class ProofSettings:
    """The cost of one challenge.

    cost is the PBKDF2 iteration count of one try. The counter that
    solves a challenge is a random integer from counter_low until
    counter_high, with counter_high not included, thus the browser does
    that count of tries. lifetime_seconds is the time from the issue of
    a challenge to its end.
    """

    cost: int
    counter_low: int
    counter_high: int
    lifetime_seconds: int


DEPLOYED = ProofSettings(cost=DEPLOYED_COST,
                         counter_low=DEPLOYED_COUNTER_LOW,
                         counter_high=DEPLOYED_COUNTER_HIGH,
                         lifetime_seconds=LIFETIME_SECONDS)


@dataclass(frozen=True)
class ProofKeys:
    """The two HMAC keys of the proofs, made from the one secret.

    challenge signs the parameters of a challenge. derived signs the
    key that the solving counter gives, thus the check of a payload is
    one HMAC and not a second derivation.
    """

    challenge: bytes
    derived: bytes


@dataclass(frozen=True)
class Proof:
    """A payload that agrees with a challenge of this server.

    signature is the HMAC of the challenge, and the ledger of spent
    proofs keys on it. expires_at is the end of the challenge, in Unix
    seconds.
    """

    signature: str
    expires_at: int


def keys_from_secret(secret: str | None) -> ProofKeys | None:
    """The two keys of a secret, or None when the secret is empty."""
    if not secret:
        return None
    raw = secret.encode("utf-8")
    return ProofKeys(
        challenge=hmac.new(raw, _CHALLENGE_LABEL, hashlib.sha256).digest(),
        derived=hmac.new(raw, _DERIVED_LABEL, hashlib.sha256).digest())


def make_challenge(keys: ProofKeys, settings: ProofSettings,
                   instant: datetime.datetime) -> dict:
    """One signed challenge, as the JSON object the widget reads.

    The server picks the counter and derives its key one time, at the
    cost of one try. The challenge holds the first half of that key and
    an HMAC of the full key, thus the browser must find the counter,
    and the check of its answer does not derive again.
    """
    counter = settings.counter_low + secrets.randbelow(
        settings.counter_high - settings.counter_low)
    expires_at = int(instant.timestamp()) + settings.lifetime_seconds
    challenge = altcha.create_challenge(
        ALGORITHM, settings.cost, counter=counter, expires_at=expires_at,
        hmac_secret=keys.challenge, hmac_key_secret=keys.derived)
    return challenge.to_dict()


def check_proof(payload: object, keys: ProofKeys,
                instant: datetime.datetime) -> Proof | None:
    """The proof of a payload, or None when the payload does not agree.

    payload is the text of the sign-up body. A text that is not base64
    JSON of the ALTCHA shape, a challenge with no end or an end before
    instant, a signature that is not this server's, and a derived key
    that is not the key of the challenge each give None. The server
    clock decides the end, and the library also checks it.
    """
    if not isinstance(payload, str) or len(payload) > PAYLOAD_MAX_CHARS:
        return None
    try:
        parsed = altcha.Payload.from_base64(payload)
    except (ValueError, KeyError, TypeError, AttributeError,
            UnicodeDecodeError, binascii.Error, RecursionError):
        return None
    expires_at = parsed.challenge.parameters.expires_at
    if type(expires_at) is not int or expires_at <= instant.timestamp():
        return None
    signature = parsed.challenge.signature
    if not isinstance(signature, str):
        return None
    result = altcha.verify_solution(parsed, keys.challenge,
                                    hmac_key_secret=keys.derived)
    if not result.verified:
        return None
    return Proof(signature=signature, expires_at=expires_at)


class SpentProofs:
    """The proofs that made an account, each kept until its end.

    One solved challenge makes one account at most (decision D5). A
    sign-up holds its proof while the store work goes on, and gives it
    back when the store refuses the account, thus a refused name does
    not cost the person a second proof. The ledger is in the memory of
    the process. A start of the server empties it, and a proof that
    made an account before the start can then make one more before its
    end. The caps of spec A2 decision D11 also count that account.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until: dict[str, int] = {}

    def hold(self, proof: Proof, instant: datetime.datetime) -> bool:
        """Hold a proof for one sign-up, and tell if the hold took effect.

        The answer is no when the proof is spent or held.
        """
        now = instant.timestamp()
        with self._lock:
            for signature in [key for key, until in self._until.items()
                              if until <= now]:
                del self._until[signature]
            if proof.signature in self._until:
                return False
            self._until[proof.signature] = proof.expires_at
            return True

    def give_back(self, proof: Proof) -> None:
        """Free a held proof: the sign-up that held it made no account."""
        with self._lock:
            self._until.pop(proof.signature, None)
