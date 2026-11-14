"""The password rules (spec A2 section 5.1).

Pure functions of strings: the normalization, the refusal causes, and
the reader of the table of usual passwords. No digest is here. The
digest module keeps that work, thus a test of a rule spends no slow
digest.
"""

import unicodedata
from collections.abc import Container
from pathlib import Path

# Ruling 4 and decision D3 of spec A2.
PASSWORD_MIN = 12
PASSWORD_MAX = 128

USUAL_PASSWORDS_PATH = Path(__file__).parent / "data" / "usual-passwords.txt"

PASSWORD_RULE = "password-rule"
PASSWORD_USUAL = "password-usual"


def normalize_password(value: object) -> str | None:
    """The NFKC shape of one typed password, or None for a value that
    is not text.

    Two keyboards can send one password as two code point sequences
    that look the same. NFKC gives one sequence for the two, thus the digest of
    the sign-up agrees with the digest of each sign-in.
    """
    if not isinstance(value, str):
        return None
    return unicodedata.normalize("NFKC", value)


def password_refusal(password: str, username: str,
                     usual: Container[str]) -> str | None:
    """The cause that refuses one password, or None for a good one.

    password is the NFKC shape. username is the legal name of the
    account. usual holds the casefold shape of each usual password.

    The length counts code points. A character that is not printable is
    refused, and the space is printable. A password that holds the
    username is refused, in each mix of capitals. No rule looks at
    character classes (spec A2 section 5.1).
    """
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        return PASSWORD_RULE
    if not password.isprintable():
        return PASSWORD_RULE
    folded = password.casefold()
    if username and username in folded:
        return PASSWORD_RULE
    if folded in usual:
        return PASSWORD_USUAL
    return None


def load_usual_passwords(path: Path = USUAL_PASSWORDS_PATH) -> frozenset[str]:
    """The table of usual passwords, one casefold entry for each line.

    Raises OSError when the file is not there: a server with no table
    accepts each usual password, and that must not occur quietly.
    """
    text = path.read_text(encoding="utf-8")
    return frozenset(line for line in text.split("\n") if line)
