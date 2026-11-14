"""The limits of the server (spec BR1 section 4, spec PL1 section 1).

The window limiter counts uses in a sliding window, for each key
and for the full process, and refuses when one of the two counts gets
to its cap. Two uses share it. A device code is eight characters from
a 31-character alphabet and lives ten minutes, thus a guess is hopeless
one at a time, and the limiter keeps it hopeless in bulk by counting
redemptions that do not succeed. Practice scoring spends provider
quota that a close needs, thus the limiter counts scores for each
player.

In memory, for one process: the server is one process (spec S2
ruling 1). A new start empties the counts, and that is not a hole a
guess can use - the global cap holds across each window.

The body cap and the record caps guard the paths that accept new
records. They do not enter Layer 0, which is frozen: a stored
submission must validate forever, whatever these values become.
"""

import asyncio
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from typing import Any

WINDOW_SECONDS = 10 * 60
CLIENT_CAP = 10
GLOBAL_CAP = 200

# The practice limit (spec PL1 section 1).
PRACTICE_WINDOW_SECONDS = 60 * 60
PRACTICE_PLAYER_CAP = 30
PRACTICE_GLOBAL_CAP = 600

# The body cap: the record caps below at about 40 bytes for a point
# fit in it, and so does the avatar cap of the store.
BODY_BYTE_CAP = 1_048_576
BODY_READ_SECONDS = 30.0

# The record caps. A worst-path zigzag costs about 0.08 ms for each
# point in Layer 0 (measured 2026-11-03), thus 1.6 s at most.
STROKE_CAP = 2_000
POINT_CAP = 20_000

# The password counters (spec A2 section 9.2). Failures for a client
# address and for the process use the window and the two caps at the
# top of this module. A username has its own cap (decision D10), and
# the accounts made have a window and two caps of their own (decision
# D11).
NAME_FAILURE_CAP = 10
SIGNUP_WINDOW_SECONDS = 24 * 60 * 60
SIGNUP_CLIENT_CAP = 10
SIGNUP_GLOBAL_CAP = 1_000
_NAME_KEY = re.compile(r"[a-z0-9-]{1,64}")

_BODY_TOO_LARGE = b'{"cause":"body-too-large"}'
_BODY_TOO_SLOW = b'{"cause":"body-too-slow"}'

_INVITE_PATH = re.compile(r"/join/[^\s?\"]*")


@dataclass
class WindowLimiter:
    """Counts uses in a sliding window, for each key and in total.

    A container of counts in the shell: the handlers share one, and
    the lock serializes the threads that can touch it.
    """

    window_seconds: float = WINDOW_SECONDS
    client_cap: int = CLIENT_CAP
    global_cap: int = GLOBAL_CAP
    clock: Callable[[], float] = time.monotonic
    _by_key: dict[str, deque] = field(default_factory=dict)
    _total: deque = field(default_factory=deque)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _trim(self, times: deque, now: float) -> None:
        while times and now - times[0] >= self.window_seconds:
            times.popleft()

    def allowed(self, key: str) -> bool:
        """The key can go again: the two counts are below their caps."""
        with self._lock:
            now = self.clock()
            self._trim(self._total, now)
            times = self._by_key.get(key)
            if times is not None:
                self._trim(times, now)
                if not times:
                    del self._by_key[key]
                    times = None
            client_count = 0 if times is None else len(times)
            return client_count < self.client_cap \
                and len(self._total) < self.global_cap

    def record(self, key: str) -> None:
        """Count one use, for the key and in total."""
        with self._lock:
            now = self.clock()
            self._by_key.setdefault(key, deque()).append(now)
            self._total.append(now)
            if len(self._by_key) > self.global_cap:
                self._sweep(now)

    def _sweep(self, now: float) -> None:
        """Drop each key with no use in the window.

        The global cap holds the live keys to global_cap at most, thus
        this removal at that count keeps the table bounded, with each
        count of keys.
        """
        for key in [name for name, times in self._by_key.items()
                    if not times or now - times[-1] >= self.window_seconds]:
            del self._by_key[key]


def client_key(peer: str | None, forwarded_for: str | None) -> str:
    """The address to count one redemption against.

    Behind the edge, the peer is the loopback address and Caddy
    appends the client's address to X-Forwarded-For. The last entry
    is the one the edge wrote. The entries before it come from the
    client and prove nothing. With no edge in front, the peer is the
    client.
    """
    if peer in ("127.0.0.1", "::1") and forwarded_for:
        last = forwarded_for.split(",")[-1].strip()
        if last:
            return last
    return peer or "unknown"


def practice_limiter() -> WindowLimiter:
    """A limiter with the practice values of spec PL1 section 1."""
    return WindowLimiter(window_seconds=PRACTICE_WINDOW_SECONDS,
                         client_cap=PRACTICE_PLAYER_CAP,
                         global_cap=PRACTICE_GLOBAL_CAP)


def name_failure_limiter() -> WindowLimiter:
    """A limiter of failures for each username (spec A2 decision D10)."""
    return WindowLimiter(client_cap=NAME_FAILURE_CAP)


def signup_limiter() -> WindowLimiter:
    """A limiter of the accounts made (spec A2 decision D11)."""
    return WindowLimiter(window_seconds=SIGNUP_WINDOW_SECONDS,
                         client_cap=SIGNUP_CLIENT_CAP,
                         global_cap=SIGNUP_GLOBAL_CAP)


def name_key(username: object) -> str:
    """The key to count one failure against, for a typed username.

    Text that cannot be a stored name shares one key, thus a caller
    cannot fill the table with keys of its own invention.
    """
    if isinstance(username, str) and _NAME_KEY.fullmatch(username.lower()):
        return username.lower()
    return "(not a name)"


def record_caps_refusal(record: object, *, stroke_cap: int = STROKE_CAP,
                        point_cap: int = POINT_CAP) -> str | None:
    """The refusal text for a wire record above a cap, or None.

    The check counts and does not validate: a record with a bad shape
    gets None here and the bad-shape refusal from Layer 0, thus one
    module owns that wording. It stops at the first value above the
    cap, thus its cost is bounded too.
    """
    if not isinstance(record, dict):
        return None
    strokes = record.get("canvas_strokes")
    if not isinstance(strokes, list):
        return None
    if len(strokes) > stroke_cap:
        return f"{len(strokes)} strokes, limit {stroke_cap}"
    points = 0
    for stroke in strokes:
        path = stroke.get("points") if isinstance(stroke, dict) else None
        if isinstance(path, list):
            points += len(path)
            if points > point_cap:
                return f"more than {point_cap} points"
    return None


class RedactInvitePaths(logging.Filter):
    """Replace the token in each invite path of an access line.

    Uvicorn gives the path in the arguments of its record. An invite
    is a credential until its token turns, thus it must not enter the
    journal.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _INVITE_PATH.sub("/join/[redacted]", value)
                if isinstance(value, str) else value
                for value in record.args)
        return True


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


async def _refuse(send: Send, status: int, body: bytes) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", ()):
        if name == b"content-length":
            return int(value) if value.isdigit() else None
    return None


class BodyCap:
    """Read each body in full, with a byte cap and a deadline.

    Plain ASGI, because a handler that reads the stream itself catches
    each error of a wrapped read and calls it a bad shape. The app runs
    after the last byte, thus no handler waits on a slow client, and
    this holds the cap at most for each connection.

    The paths in the last argument keep their own stream check: the
    avatar path has its own cap and its own refusal.
    """

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]],
                 *, cap: int = BODY_BYTE_CAP,
                 seconds: float = BODY_READ_SECONDS,
                 exempt: tuple[str, ...] = ()) -> None:
        self.app = app
        self.cap = cap
        self.seconds = seconds
        self.exempt = exempt

    async def __call__(self, scope: Scope, receive: Receive,
                       send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.exempt:
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.cap:
            await _refuse(send, 413, _BODY_TOO_LARGE)
            return
        messages: list[Message] = []
        received = 0
        try:
            async with asyncio.timeout(self.seconds):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    received += len(message.get("body", b""))
                    if received > self.cap:
                        await _refuse(send, 413, _BODY_TOO_LARGE)
                        return
                    messages.append(message)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await _refuse(send, 408, _BODY_TOO_SLOW)
            return
        pending = iter(messages)

        async def replay() -> Message:
            following = next(pending, None)
            return await receive() if following is None else following

        await self.app(scope, replay, send)
