"""The invite token and the session cookie (spec M1 section 4).

Pure functions of strings: the token shape, its one unambiguous
division, the digest the store keeps, the constant-time compare, and
the cookie header. No file read, no clock, and no HTTP object. The
store holds the record and the server holds the handlers.
"""

import re
import secrets

from core.canonical import sha256_hex

SECRET_BYTES = 32
SESSION_COOKIE = "sv_session"
SESSION_MAX_AGE = 180 * 24 * 60 * 60

# The player alphabet holds no dot and the URL-safe secret alphabet
# holds no dot, thus an accepted token holds one dot and the
# division is forced. Two division points want a dot in a group
# with no dot in its character class, which cannot occur.
#
# fullmatch, not match: the dollar sign also matches before a
# newline at the end, and a token arrives from the network.
_TOKEN_RULE = re.compile(r"([a-z0-9-]{1,64})\.([A-Za-z0-9_-]{43})")


def token_hash(secret: str) -> str:
    """The sha256 hex digest of one invite secret.

    A secret of 32 random bytes wants no slow password hash. There
    is no dictionary to walk, thus the added cost buys nothing.
    """
    return sha256_hex(secret)


def mint_token(player: str, *, secret: str | None = None) -> tuple[str, str]:
    """One invite token and the digest for the store.

    secret arrives as an argument in the manner of open_day's
    pick_seed: the random path is the default, and a fixed secret
    makes a byte-equal compare of two worlds possible. The caller
    answers the token one time and stores the digest alone.
    """
    chosen = secrets.token_urlsafe(SECRET_BYTES) if secret is None else secret
    return f"{player}.{chosen}", token_hash(chosen)


def parse_token(token: object) -> tuple[str, str] | None:
    """The player name and the secret, or None for other text."""
    if not isinstance(token, str):
        return None
    found = _TOKEN_RULE.fullmatch(token)
    return None if found is None else (found.group(1), found.group(2))


def secret_matches(secret: str, stored_hash: str) -> bool:
    """Compare one invite secret against the stored digest.

    The compare runs on two hex digests of equal width, thus the
    stored value gives up no content and no length.
    """
    return secrets.compare_digest(token_hash(secret), stored_hash)


def constant_time_equal(given: object, expected: str) -> bool:
    """Compare two secrets in constant time, with no length leak.

    The compare runs on the two digests and not on the two values,
    thus it costs the same for each pair of inputs. It also raises
    nothing: compare_digest refuses a str with characters above
    ASCII, and an Authorization header arrives from the network.
    """
    if not isinstance(given, str):
        return False
    return secrets.compare_digest(token_hash(given), token_hash(expected))


def session_cookie_header(token: str, *, secure: bool = True) -> str:
    """The Set-Cookie value for one session (spec M1 section 4).

    HttpOnly stops script access. Secure pins the transport.
    SameSite=Lax lets the invite URL's own navigation send the
    cookie, and a POST from a different site cannot send it. Path
    is the site root, thus the cookie rides each fetch to the same
    site and the client handles no credential.

    The transport flag turns off for the offline browser tests,
    which speak http to a loopback port. Chromium stores a Secure
    cookie from such a port and then does not send it back, thus
    the test fails for a cause with no connection to the code it
    examines. The default is the deployed attribute set.

    A __Host- prefix can make the browser hold the three attributes
    for us. It is one word away and it is not here, because it also
    refuses the cookie on a bare-address staging box on http.
    """
    parts = [f"{SESSION_COOKIE}={token}", "Path=/"]
    if secure:
        parts.append("Secure")
    parts.extend(["HttpOnly", "SameSite=Lax", f"Max-Age={SESSION_MAX_AGE}"])
    return "; ".join(parts)
