"""The password digest (spec A2 section 5.2).

The server does not keep a password. It keeps one Argon2id digest for
each player, made from the password after HMAC-SHA-256 with the
pepper. The pepper is a deployment secret: it arrives as an argument
here, and the start-up path reads it from the environment.

PasswordDigester is the interface that the handlers use. The tests
give them a digester with no slow work, thus the suite keeps its
speed and this module alone computes Argon2id.
"""

import hashlib
import hmac
import threading
from dataclasses import dataclass, field
from typing import Protocol

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# Decision D5 of spec A2: one configuration of the OWASP table.
ARGON2_MEMORY_KIB = 19_456
ARGON2_ITERATIONS = 2
ARGON2_LANES = 1
ARGON2_SALT_BYTES = 16
ARGON2_DIGEST_BYTES = 32

# Decision D7 of spec A2: the digests that the server computes at one
# time. One digest holds 19 MiB, and the box has one processor.
DIGESTS_AT_ONE_TIME = 2

# Decision D6 of spec A2: the environment name of the pepper.
PEPPER_ENVIRONMENT_NAME = "STARVECTOR_PASSWORD_PEPPER"

# The password of the fixed digest (spec A2 section 9.3). It is not a
# credential: no account has this digest.
_ABSENT_PASSWORD = "no account has this password"


class PasswordDigester(Protocol):
    """What the sign-in handlers want from a digest module.

    digest and agrees are slow on purpose in the deployed digester. A
    caller keeps them away from the loop thread.
    """

    def digest(self, password: str) -> str:
        """The text that the credential record keeps for one password."""
        ...

    def agrees(self, password: str, stored: str) -> bool:
        """The typed password is the password of the stored digest."""
        ...

    def stale(self, stored: str) -> bool:
        """The stored digest has parameters that are not the current
        ones, thus the server writes a new digest at this sign-in."""
        ...

    def absent(self, password: str) -> None:
        """Do the work of one compare for a name with no account."""
        ...


def peppered(password: str, pepper: bytes) -> str:
    """HMAC-SHA-256 of one password with the pepper, as hex text.

    The output is 64 ASCII characters for each input, thus Argon2id
    gets no null byte and no long input.
    """
    return hmac.new(pepper, password.encode("utf-8"),
                    hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Argon2Digester:
    """Argon2id with the pepper and a cap on the digests at one time.

    A frozen record of the pepper and the two helpers. The gate is a
    counting lock: a third digest waits for one of the two before it.
    """

    pepper: bytes
    _hasher: PasswordHasher = field(init=False, repr=False, compare=False)
    _gate: threading.BoundedSemaphore = field(init=False, repr=False,
                                              compare=False)
    _absent: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.pepper, bytes) or not self.pepper:
            raise ValueError(
                "the pepper is empty - put "
                f"{PEPPER_ENVIRONMENT_NAME} in the deployment environment "
                "file")
        hasher = PasswordHasher(
            time_cost=ARGON2_ITERATIONS, memory_cost=ARGON2_MEMORY_KIB,
            parallelism=ARGON2_LANES, hash_len=ARGON2_DIGEST_BYTES,
            salt_len=ARGON2_SALT_BYTES, type=Type.ID)
        object.__setattr__(self, "_hasher", hasher)
        object.__setattr__(self, "_gate",
                           threading.BoundedSemaphore(DIGESTS_AT_ONE_TIME))
        object.__setattr__(self, "_absent", hasher.hash(
            peppered(_ABSENT_PASSWORD, self.pepper)))

    def digest(self, password: str) -> str:
        with self._gate:
            return self._hasher.hash(peppered(password, self.pepper))

    def agrees(self, password: str, stored: str) -> bool:
        with self._gate:
            try:
                return self._hasher.verify(
                    stored, peppered(password, self.pepper))
            except VerificationError:
                return False
            except InvalidHashError as error:
                # A stored digest that is not Argon2 text is a broken
                # record, not a bad password (spec A2 section 13).
                raise ValueError(
                    "a stored password digest is not Argon2 text") from error

    def stale(self, stored: str) -> bool:
        return self._hasher.check_needs_rehash(stored)

    def absent(self, password: str) -> None:
        self.agrees(password, self._absent)


def digester_from_pepper(text: str | None) -> Argon2Digester | None:
    """The deployed digester for one environment value, or None for no
    value. The start-up path decides if None is legal."""
    if not text:
        return None
    return Argon2Digester(pepper=text.encode("utf-8"))
