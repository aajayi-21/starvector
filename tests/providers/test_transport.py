"""Tests for the transport byte metering."""

import threading
from collections.abc import Iterator

import httpx
import pytest

from providers.corpora.transport import (
    ByteMeter,
    MeteredTransport,
    metered_client_factory,
)


def test_byte_meter_counts_across_threads() -> None:
    meter = ByteMeter()

    def add_many() -> None:
        for _ in range(10_000):
            meter.add(3)

    threads = [threading.Thread(target=add_many) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert meter.total == 2 * 10_000 * 3


def test_byte_meter_rejects_negative_counts() -> None:
    meter = ByteMeter()
    with pytest.raises(ValueError):
        meter.add(-1)
    assert meter.total == 0


def test_metered_transport_counts_buffered_body() -> None:
    meter = ByteMeter()
    body = b"hello world"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    transport = MeteredTransport(httpx.MockTransport(handler), meter)
    with httpx.Client(transport=transport) as client:
        response = client.get("https://example.test/image.jpg")
    assert response.content == body
    assert meter.total == len(body)


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        yield from self._chunks


def test_metered_transport_counts_streamed_body() -> None:
    meter = ByteMeter()
    chunks = [b"abc", b"defg", b"hi"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_ChunkStream(list(chunks)))

    transport = MeteredTransport(httpx.MockTransport(handler), meter)
    with httpx.Client(transport=transport) as client:
        with client.stream("GET", "https://example.test/large.bin") as response:
            received = b"".join(response.iter_bytes())
    assert received == b"abcdefghi"
    assert meter.total == len(received)


def test_metered_transport_accumulates_across_calls() -> None:
    meter = ByteMeter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"xxxx")

    transport = MeteredTransport(httpx.MockTransport(handler), meter)
    with httpx.Client(transport=transport) as client:
        client.get("https://example.test/a")
        client.get("https://example.test/b")
    assert meter.total == 8


def test_metered_client_factory_builds_new_clients() -> None:
    meter = ByteMeter()
    factory = metered_client_factory(meter, timeout=1.0)
    first = factory()
    second = factory()
    try:
        assert isinstance(first, httpx.Client)
        assert first is not second
    finally:
        first.close()
        second.close()
