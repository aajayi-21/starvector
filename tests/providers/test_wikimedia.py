"""Tests for the Wikimedia URL helpers and the fetcher. Offline only."""

import httpx
import pytest

from providers.corpora.transport import ByteMeter
from providers.corpora.wikimedia import (
    WikimediaFetchConfig,
    WikimediaFetcher,
    fetch_mode,
    thumbnail_url,
    url_extension,
)
from providers.protocols import MaterializedImage, MaterializeFailure, SourceRecord

COMMONS_URL = "https://upload.wikimedia.org/wikipedia/commons/b/bc/Grand_Cany%C3%B3n.jpg"
GIF_URL = "https://upload.wikimedia.org/wikipedia/commons/1/1a/Anim.gif"
SVG_URL = "https://upload.wikimedia.org/wikipedia/commons/c/cd/Diagram.svg"

BASE_CONFIG = WikimediaFetchConfig(
    thumbnail_width=1280,
    user_agent="starvector-tests/0.1 (test@example.test)",
    max_concurrency=2,
    timeout_seconds=5.0,
    retry_limit=2,
    max_fetch_bytes=10_000_000,
)


def _record(source_key: str) -> SourceRecord:
    return SourceRecord(
        source_key=source_key,
        claimed_width=1000,
        claimed_height=800,
        captions=(),
        attribution={},
    )


def test_thumbnail_url_keeps_percent_encoding() -> None:
    assert thumbnail_url(COMMONS_URL, 1280) == (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bc/"
        "Grand_Cany%C3%B3n.jpg/1280px-Grand_Cany%C3%B3n.jpg"
    )


def test_thumbnail_url_other_project() -> None:
    url = "https://upload.wikimedia.org/wikipedia/en/0/0f/Example_photo.png"
    assert thumbnail_url(url, 640) == (
        "https://upload.wikimedia.org/wikipedia/en/thumb/0/0f/"
        "Example_photo.png/640px-Example_photo.png"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a/ab/File.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bc/X.jpg/300px-X.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/x/xz/File.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/b/cc/File.jpg",
        "http://upload.wikimedia.org/wikipedia/commons/b/bc/File.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/b/bc/",
    ],
)
def test_thumbnail_url_rejects_other_shapes(url: str) -> None:
    with pytest.raises(ValueError):
        thumbnail_url(url, 1280)


@pytest.mark.parametrize(
    ("url", "extension"),
    [
        ("https://upload.wikimedia.org/wikipedia/commons/b/bc/A.JPG", "jpg"),
        ("https://example.test/path/photo.jpeg?width=3", "jpeg"),
        ("https://example.test/path/archive.tar.gz", "gz"),
        ("https://example.test/no-extension", ""),
        ("https://example.test/photo.PNG#frag", "png"),
    ],
)
def test_url_extension(url: str, extension: str) -> None:
    assert url_extension(url) == extension


@pytest.mark.parametrize(
    ("extension", "mode"),
    [
        ("jpg", "thumbnail"),
        ("jpeg", "thumbnail"),
        ("png", "thumbnail"),
        ("webp", "thumbnail"),
        ("gif", "original"),
        ("tif", "original"),
        ("tiff", "original"),
        ("bmp", "original"),
        ("svg", "unsupported"),
        ("ogg", "unsupported"),
        ("", "unsupported"),
    ],
)
def test_fetch_mode(extension: str, mode: str) -> None:
    assert fetch_mode(extension) == mode


def test_fetcher_thumbnail_mode_gets_thumbnail_url() -> None:
    meter = ByteMeter()
    seen: list[str] = []
    body = b"\xff\xd8fake-jpeg-bytes"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=body)

    fetcher = WikimediaFetcher(BASE_CONFIG, meter, transport=httpx.MockTransport(handler))
    [result] = fetcher.fetch_many([_record(COMMONS_URL)])
    expected_url = thumbnail_url(COMMONS_URL, BASE_CONFIG.thumbnail_width)
    assert isinstance(result, MaterializedImage)
    assert result.image_bytes == body
    assert result.retrieval_note == f"GET {expected_url} thumb_width=1280"
    assert seen == [expected_url]


def test_fetcher_original_mode_gets_source_url() -> None:
    meter = ByteMeter()
    seen: list[str] = []
    body = b"GIF89a-fake"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=body)

    fetcher = WikimediaFetcher(BASE_CONFIG, meter, transport=httpx.MockTransport(handler))
    [result] = fetcher.fetch_many([_record(GIF_URL)])
    assert isinstance(result, MaterializedImage)
    assert result.image_bytes == body
    assert result.retrieval_note == f"GET {GIF_URL} original"
    assert seen == [GIF_URL]


def test_fetcher_unsupported_extension_makes_no_http_traffic() -> None:
    meter = ByteMeter()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"never-served")

    fetcher = WikimediaFetcher(BASE_CONFIG, meter, transport=httpx.MockTransport(handler))
    [result] = fetcher.fetch_many([_record(SVG_URL)])
    assert result == MaterializeFailure(SVG_URL, "unsupported-media-type", "svg")
    assert seen == []
    assert meter.total == 0


def test_fetcher_oversized_body_is_fetch_too_large() -> None:
    meter = ByteMeter()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 100)

    config = BASE_CONFIG._replace(max_fetch_bytes=10)
    fetcher = WikimediaFetcher(config, meter, transport=httpx.MockTransport(handler))
    [result] = fetcher.fetch_many([_record(COMMONS_URL)])
    assert result == MaterializeFailure(COMMONS_URL, "fetch-too-large", "10")


def test_fetcher_404_is_fetch_error_without_retries() -> None:
    meter = ByteMeter()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(404)

    fetcher = WikimediaFetcher(BASE_CONFIG, meter, transport=httpx.MockTransport(handler))
    [result] = fetcher.fetch_many([_record(COMMONS_URL)])
    assert result == MaterializeFailure(COMMONS_URL, "fetch-error", "HTTP 404")
    assert len(seen) == 1


def test_fetcher_retries_429_then_succeeds() -> None:
    meter = ByteMeter()
    seen: list[str] = []
    body = b"ok-after-retry"

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if len(seen) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=body)

    fetcher = WikimediaFetcher(BASE_CONFIG, meter, transport=httpx.MockTransport(handler))
    [result] = fetcher.fetch_many([_record(COMMONS_URL)])
    assert isinstance(result, MaterializedImage)
    assert result.image_bytes == body
    assert len(seen) == 2


def test_fetcher_exhausted_retries_become_fetch_error() -> None:
    meter = ByteMeter()
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(503, headers={"Retry-After": "0"})

    config = BASE_CONFIG._replace(retry_limit=1)
    fetcher = WikimediaFetcher(config, meter, transport=httpx.MockTransport(handler))
    [result] = fetcher.fetch_many([_record(COMMONS_URL)])
    assert result == MaterializeFailure(COMMONS_URL, "fetch-error", "HTTP 503")
    assert len(seen) == 2


def test_fetch_many_results_line_up_with_input() -> None:
    meter = ByteMeter()
    jpg_body = b"jpg-body"
    gif_body = b"gif-body-bytes"
    missing_png = "https://upload.wikimedia.org/wikipedia/commons/2/2b/Gone.png"

    def handler(request: httpx.Request) -> httpx.Response:
        if "Gone.png" in str(request.url):
            return httpx.Response(404)
        if str(request.url).endswith(".gif"):
            return httpx.Response(200, content=gif_body)
        return httpx.Response(200, content=jpg_body)

    fetcher = WikimediaFetcher(BASE_CONFIG, meter, transport=httpx.MockTransport(handler))
    records = [
        _record(COMMONS_URL),
        _record(SVG_URL),
        _record(missing_png),
        _record(GIF_URL),
    ]
    results = fetcher.fetch_many(records)
    assert len(results) == 4
    assert isinstance(results[0], MaterializedImage)
    assert results[0].source_key == COMMONS_URL
    assert results[0].image_bytes == jpg_body
    assert results[1] == MaterializeFailure(SVG_URL, "unsupported-media-type", "svg")
    assert results[2] == MaterializeFailure(missing_png, "fetch-error", "HTTP 404")
    assert isinstance(results[3], MaterializedImage)
    assert results[3].source_key == GIF_URL
    assert results[3].image_bytes == gif_body


def test_meter_counts_fetched_body_bytes() -> None:
    meter = ByteMeter()
    body = b"z" * 1234

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    fetcher = WikimediaFetcher(BASE_CONFIG, meter, transport=httpx.MockTransport(handler))
    fetcher.fetch_many([_record(COMMONS_URL)])
    assert meter.total == len(body)
    fetcher.fetch_many([_record(GIF_URL)])
    assert meter.total == 2 * len(body)
