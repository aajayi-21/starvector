"""Transport-level byte metering for corpus adapters.

Spec: docs/specs/pool-curation.md section 7 (U1). A corpus adapter
counts the bytes it retrieves at its transport layer. This module has
the counter and the httpx transport wrapper that feeds it.
"""

import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx


class ByteMeter:
    """Monotone byte counter, safe across threads (U1)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total = 0

    def add(self, n: int) -> None:
        """Add a non-negative byte count to the total."""
        if n < 0:
            raise ValueError(f"byte count must be non-negative, got {n}")
        with self._lock:
            self._total += n

    @property
    def total(self) -> int:
        """The byte count so far."""
        with self._lock:
            return self._total


class _MeteredStream(httpx.SyncByteStream):
    """A response stream that counts each chunk into the meter."""

    def __init__(self, inner: httpx.SyncByteStream, meter: ByteMeter) -> None:
        self._inner = inner
        self._meter = meter

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._inner:
            self._meter.add(len(chunk))
            yield chunk

    def close(self) -> None:
        self._inner.close()


class MeteredTransport(httpx.BaseTransport):
    """An httpx transport that counts response body bytes into the meter.

    The inner transport does the network work. For a body that httpx
    buffered at construction, the count occurs immediately. For a
    streamed body, the count occurs chunk by chunk while the caller
    reads it.
    """

    def __init__(self, inner: httpx.BaseTransport, meter: ByteMeter) -> None:
        self._inner = inner
        self._meter = meter

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Delegate to the inner transport and count the response body."""
        response = self._inner.handle_request(request)
        buffered = getattr(response, "_content", None)
        if buffered is not None:
            # httpx buffers the body at construction when a response is
            # built from in-memory content. Reads then come from that
            # buffer, not from the stream, thus the count happens here.
            self._meter.add(len(buffered))
        elif isinstance(response.stream, httpx.SyncByteStream):
            response.stream = _MeteredStream(response.stream, self._meter)
        else:
            raise TypeError(
                "response has no buffered content and its stream is not a "
                "SyncByteStream - cannot meter this response"
            )
        return response

    def close(self) -> None:
        """Close the inner transport."""
        self._inner.close()


def metered_client_factory(
    meter: ByteMeter, **client_kwargs: Any
) -> Callable[[], httpx.Client]:
    """Build a factory of httpx clients that count bytes into the meter.

    The output is a zero-argument function. Each use builds a new
    httpx.Client with a MeteredTransport around a new
    httpx.HTTPTransport. All other keyword arguments go to the
    httpx.Client constructor.
    """

    def factory() -> httpx.Client:
        transport = MeteredTransport(httpx.HTTPTransport(), meter)
        return httpx.Client(transport=transport, **client_kwargs)

    return factory
