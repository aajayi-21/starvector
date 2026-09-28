"""The invite token, the session, and the device code (spec M1
section 4, spec BR1 section 4).

Pure functions of strings: the token shape, its one unambiguous
division, the digest the store keeps, the constant-time compare, the
cookie headers, the device code, and the device label. No file read,
no clock, and no HTTP object. The store holds the records and the
server holds the handlers.

Two credentials share one shape, "<player>.<secret>". An invite
token names a player record and its secret meets the record's
digest. A session value names a session record below the player,
and its secret's digest is that record's file name. The cookie
holds a session value alone - not the invite (spec BR1).
"""

import re
import secrets

from core.canonical import sha256_hex

SECRET_BYTES = 32
SESSION_COOKIE = "sv_session"
SESSION_MAX_AGE = 180 * 24 * 60 * 60

# The device code (spec BR1 section 4): eight characters from an
# alphabet with no 0, O, 1, I, or L, thus a code read off one screen
# and typed on a second one has no look-alike pair. 31 ** 8 is about
# 8.5e11 codes, and a code lives ten minutes and works one time.
DEVICE_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
DEVICE_CODE_LENGTH = 8
DEVICE_CODE_SECONDS = 10 * 60
_DEVICE_CODE_RULE = re.compile(
    f"[{DEVICE_CODE_ALPHABET}]{{{DEVICE_CODE_LENGTH}}}")

_LABEL_LIMIT = 40

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


def clear_cookie_header(*, secure: bool = True) -> str:
    """The Set-Cookie value that removes the session cookie.

    The same name, path, and flags as the session header, thus the
    browser matches the one cookie, and Max-Age=0 removes it.
    """
    parts = [f"{SESSION_COOKIE}=", "Path=/"]
    if secure:
        parts.append("Secure")
    parts.extend(["HttpOnly", "SameSite=Lax", "Max-Age=0"])
    return "; ".join(parts)


def mint_session(player: str, *,
                 secret: str | None = None) -> tuple[str, str]:
    """One session value for the cookie and the digest the store keys on.

    The value has the invite token's shape, thus parse_token divides
    it. secret arrives as an argument for the tests that pin a
    session, in the manner of mint_token.
    """
    chosen = secrets.token_urlsafe(SECRET_BYTES) if secret is None else secret
    return f"{player}.{chosen}", token_hash(chosen)


def make_device_code() -> str:
    """Eight random characters from the device-code alphabet."""
    return "".join(secrets.choice(DEVICE_CODE_ALPHABET)
                   for _ in range(DEVICE_CODE_LENGTH))


def normalize_device_code(text: object) -> str | None:
    """A typed code in its stored shape, or None for other text.

    Capitals, spaces, and hyphens do not count, thus "abcd-efgh" and
    "ABCD EFGH" are one code. A character that is not in the
    alphabet makes the text not a code at all.
    """
    if not isinstance(text, str) or len(text) > 32:
        return None
    compact = "".join(text.split()).replace("-", "").upper()
    return compact if _DEVICE_CODE_RULE.fullmatch(compact) else None


def display_device_code(code: str) -> str:
    """The code in two groups of four, for a person to read."""
    return f"{code[:4]}-{code[4:]}"


def device_code_hash(code: str) -> str:
    """The digest the store keys a device code on."""
    return sha256_hex(f"device-code:{code}")


def device_label(user_agent: object) -> str:
    """A short name for a device, from its User-Agent header.

    The store keeps this label alone and not the header: it is sufficient
    for a player to tell two sessions apart. The match is on plain
    substrings, in a fixed sequence, because each browser's string
    names the engines it copies too.
    """
    if not isinstance(user_agent, str) or user_agent == "":
        return "Unknown device"
    text = user_agent
    if "iPhone" in text:
        system = "iPhone"
    elif "iPad" in text:
        system = "iPad"
    elif "Android" in text:
        system = "Android"
    elif "CrOS" in text:
        system = "ChromeOS"
    elif "Macintosh" in text or "Mac OS X" in text:
        system = "Mac"
    elif "Windows" in text:
        system = "Windows"
    elif "Linux" in text:
        system = "Linux"
    else:
        system = None
    if "Edg/" in text or "EdgiOS" in text or "EdgA" in text:
        browser = "Edge"
    elif "Firefox/" in text or "FxiOS" in text:
        browser = "Firefox"
    elif "OPR/" in text:
        browser = "Opera"
    elif "Chrome/" in text or "CriOS" in text:
        browser = "Chrome"
    elif "Safari/" in text:
        browser = "Safari"
    else:
        browser = None
    if browser is None and system is None:
        return "Unknown device"
    if system is None:
        return browser
    return f"{browser or 'Browser'} on {system}"[:_LABEL_LIMIT]

