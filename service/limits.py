"""The failure limiter for the device-code redemption (spec BR1 section 4).

A device code is eight characters from a 31-character alphabet and
lives ten minutes, thus a guess is hopeless one at a time. This
limiter keeps it hopeless in bulk: it counts redemptions that do not
succeed in a sliding window, for each client address and for the
full process, and refuses when one of the two counts gets to its cap.
A success does not count.

In memory, for one process: the server is one process (spec S2
ruling 1). A new start empties the counts, and that is not a hole a
guess can use - the global cap holds across each window.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

WINDOW_SECONDS = 10 * 60
CLIENT_CAP = 10
GLOBAL_CAP = 200


@dataclass
class FailureLimiter:
    """Counts failures in a sliding window, for each key and in total.

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
        """The key can try again: the two counts are below their caps."""
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

    def record_failure(self, key: str) -> None:
        """Count one redemption that did not succeed, for the key and
        in total."""
        with self._lock:
            now = self.clock()
            self._by_key.setdefault(key, deque()).append(now)
            self._total.append(now)
            if len(self._by_key) > self.global_cap:
                self._sweep(now)

    def _sweep(self, now: float) -> None:
        """Drop each key with no failure in the window.

        The global cap holds the live keys to global_cap at most, thus
        this removal at that count keeps the table bounded, with each
        count of addresses that guess.
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
