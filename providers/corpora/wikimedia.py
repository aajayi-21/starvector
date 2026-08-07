"""Wikimedia file retrieval for the corpus adapters.

Spec: docs/specs/pool-curation.md section 7 and open decision D9. Pure
URL helpers select the fetch mode and build the thumbnail URL. The
fetcher retrieves image bytes in one bounded batch with retries and a
byte limit, and counts transport bytes into a shared ByteMeter (U1).
"""

import re
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import httpx

from providers.corpora.transport import ByteMeter, MeteredTransport
from providers.protocols import MaterializedImage, MaterializeFailure, SourceRecord

_UPLOAD_URL_PATTERN = re.compile(
    r"^(https://upload\.wikimedia\.org/wikipedia/)"
    r"([^/]+)/([0-9a-f])/([0-9a-f]{2})/([^/]+)$"
)

_THUMBNAIL_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp"})
_ORIGINAL_EXTENSIONS = frozenset({"gif", "tif", "tiff", "bmp"})

# Retry on rate limits, server errors, and timeouts. All other HTTP
# statuses become record-level values immediately (R14).
_RETRY_STATUS_CODES = frozenset({429} | set(range(500, 600)))
_BACKOFF_INITIAL_SECONDS = 0.5
_BACKOFF_LIMIT_SECONDS = 8.0


def thumbnail_url(original_url: str, width: int) -> str:
    """The Wikimedia thumbnail URL for one upload.wikimedia.org file URL.

    The input shape is
    ``https://upload.wikimedia.org/wikipedia/<project>/<a>/<ab>/<name>``
    and the output shape is
    ``.../wikipedia/<project>/thumb/<a>/<ab>/<name>/<width>px-<name>``.
    Percent-encoded characters stay verbatim. A URL with a different
    shape raises ValueError.
    """
    if width < 1:
        raise ValueError(f"width must be positive, got {width}")
    parsed = _UPLOAD_URL_PATTERN.match(original_url)
    if parsed is None:
        raise ValueError(f"not an upload.wikimedia.org file URL: {original_url!r}")
    prefix, project, first, first_two, name = parsed.groups()
    if not first_two.startswith(first):
        raise ValueError(f"hash directories do not agree: {original_url!r}")
    return f"{prefix}{project}/thumb/{first}/{first_two}/{name}/{width}px-{name}"


def url_extension(url: str) -> str:
    """The lowercase extension of the URL path, without the dot.

    The output is an empty string when the last path segment has no dot.
    """
    path = url.split("?", 1)[0].split("#", 1)[0]
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower()


def fetch_mode(extension: str) -> str:
    """The fetch mode for one lowercase file extension.

    Extensions that the thumbnail scaler accepts get the thumbnail
    mode. Raster extensions that it does not accept get the source-file
    mode. All other extensions get the unsupported mode, and no fetch
    occurs for them.
    """
    if extension in _THUMBNAIL_EXTENSIONS:
        return "thumbnail"
    if extension in _ORIGINAL_EXTENSIONS:
        return "original"
    return "unsupported"


class WikimediaFetchConfig(NamedTuple):
    """Fetch parameters for the Wikimedia fetcher (spec section 9)."""

    thumbnail_width: int   # rendition width in pixels (D9)
    user_agent: str        # descriptive User-Agent header value (D9)
    max_concurrency: int   # worker threads for one batch
    timeout_seconds: float  # httpx timeout for one fetch
    retry_limit: int       # retries after the first try
    max_fetch_bytes: int   # limit on one fetched body


class _Retry(NamedTuple):
    """A retry signal, with the server delay when the header gave one."""

    detail: str
    delay_seconds: float | None


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """The numeric Retry-After header value in seconds, or None."""
    value = response.headers.get("Retry-After")
    if value is None or not re.fullmatch(r"[0-9]+", value.strip()):
        return None
    return float(value.strip())


class WikimediaFetcher:
    """Batched retrieval of Wikimedia image bytes.

    Each outcome is a value: a MaterializedImage or a
    MaterializeFailure (R14). The internal httpx client routes through
    a MeteredTransport, thus the response bytes count against the
    extraction budget (U1).
    """

    def __init__(
        self,
        config: WikimediaFetchConfig,
        meter: ByteMeter,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        inner = transport if transport is not None else httpx.HTTPTransport()
        self._config = config
        self._client = httpx.Client(
            transport=MeteredTransport(inner, meter),
            headers={"User-Agent": config.user_agent},
            timeout=config.timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        """Close the internal httpx client."""
        self._client.close()

    def fetch_many(
        self, records: Sequence[SourceRecord]
    ) -> list[MaterializedImage | MaterializeFailure]:
        """Fetch image bytes for each record. The output is index-aligned.

        A record-level failure becomes a MaterializeFailure value and
        does not stop the batch (R14).
        """
        if not records:
            return []
        with ThreadPoolExecutor(max_workers=self._config.max_concurrency) as executor:
            futures = [executor.submit(self._fetch_one, record) for record in records]
            return [future.result() for future in futures]

    def _fetch_one(self, record: SourceRecord) -> MaterializedImage | MaterializeFailure:
        """The fetch outcome for one record."""
        source_key = record.source_key
        extension = url_extension(source_key)
        mode = fetch_mode(extension)
        if mode == "unsupported":
            return MaterializeFailure(source_key, "unsupported-media-type", extension)
        if mode == "thumbnail":
            try:
                url = thumbnail_url(source_key, self._config.thumbnail_width)
            except ValueError as error:
                return MaterializeFailure(source_key, "fetch-error", str(error))
            note = f"GET {url} thumb_width={self._config.thumbnail_width}"
        else:
            url = source_key
            note = f"GET {url} original"
        return self._fetch_with_retries(source_key, url, note)

    def _fetch_with_retries(
        self, source_key: str, url: str, note: str
    ) -> MaterializedImage | MaterializeFailure:
        """Fetch one URL, with backoff on rate limits and server errors."""
        tries = 0
        while True:
            outcome = self._attempt(source_key, url, note)
            if not isinstance(outcome, _Retry):
                return outcome
            if tries >= self._config.retry_limit:
                return MaterializeFailure(source_key, "fetch-error", outcome.detail)
            if outcome.delay_seconds is not None:
                delay = outcome.delay_seconds
            else:
                delay = min(
                    _BACKOFF_LIMIT_SECONDS, _BACKOFF_INITIAL_SECONDS * 2**tries
                )
            time.sleep(delay)
            tries += 1

    def _attempt(
        self, source_key: str, url: str, note: str
    ) -> MaterializedImage | MaterializeFailure | _Retry:
        """One HTTP try. The output is the outcome or a retry signal.

        The body streams chunk by chunk against a byte total. A body
        larger than max_fetch_bytes stops the read immediately, and the
        outcome is the fetch-too-large value.
        """
        limit = self._config.max_fetch_bytes
        try:
            with self._client.stream("GET", url) as response:
                status = response.status_code
                if status == 200:
                    received = 0
                    chunks: list[bytes] = []
                    for chunk in response.iter_bytes():
                        received += len(chunk)
                        if received > limit:
                            return MaterializeFailure(
                                source_key, "fetch-too-large", str(limit)
                            )
                        chunks.append(chunk)
                    return MaterializedImage(source_key, b"".join(chunks), note)
                if status in _RETRY_STATUS_CODES:
                    return _Retry(f"HTTP {status}", _retry_after_seconds(response))
                return MaterializeFailure(source_key, "fetch-error", f"HTTP {status}")
        except httpx.TimeoutException as error:
            return _Retry(f"timeout: {error}", None)
        except httpx.HTTPError as error:
            return MaterializeFailure(source_key, "fetch-error", str(error))
