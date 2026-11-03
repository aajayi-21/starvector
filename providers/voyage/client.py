"""One synchronous HTTP client for the Voyage multimodal endpoint.

Spec: docs/specs/voyage-encoder.md section 3. Pacing, retries, and
backoff live here, and callers see the batched encoder protocols only.
The free credits do not apply to the Batch API, thus this client posts
to the synchronous endpoint alone.
"""

import threading
import time
from collections.abc import Callable, Mapping
from typing import NamedTuple

import httpx

from providers.voyage.errors import (VoyageRequestError, VoyageResponseError,
                                     VoyageTimeoutError)

DEFAULT_BASE_URL = "https://api.voyageai.com/v1"
_EMBEDDINGS_PATH = "/multimodalembeddings"
_BACKOFF_BASE_SECONDS = 1.0


class VoyageClientConfig(NamedTuple):
    """Transport settings for one VoyageClient. No field enters a hash.

    The two limits for each minute belong to the account, as the key
    does. The account tier moves them, and a vector does not change
    with them.
    """

    requests_per_minute: int
    tokens_per_minute: int
    timeout_seconds: float
    retry_limit: int
    base_url: str = DEFAULT_BASE_URL


class VoyageUsage(NamedTuple):
    """The accumulated credit use that the responses reported."""

    image_pixels: int
    text_tokens: int
    total_tokens: int


class _Pacer:
    """Spaces out one budget for each minute, on the monotonic clock.

    Each use books its share of the minute, thus no minute holds more
    than the budget plus one use. The retry on status 429 is the fence
    for that one use.
    """

    def __init__(self, per_minute: int, clock: Callable[[], float],
                 sleep: Callable[[float], None]) -> None:
        self._seconds_each = 60.0 / per_minute
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self, amount: int) -> None:
        """Wait for the turn of one use of the given count."""
        with self._lock:
            now = self._clock()
            start = max(now, self._next)
            self._next = start + amount * self._seconds_each
        delay = start - now
        if delay > 0.0:
            self._sleep(delay)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """The numeric Retry-After header value, or None."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return max(0.0, seconds)


def _usage_value(usage: Mapping[str, object], name: str) -> int:
    value = usage.get(name)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


class VoyageClient:
    """POST transport with pacing, retries, and credit counters.

    The API key comes from the environment at wiring time and is not
    part of provider configuration. Tests inject an httpx.MockTransport.
    """

    def __init__(
        self,
        config: VoyageClientConfig,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key:
            raise VoyageRequestError(
                "Voyage API key is missing or empty. Set VOYAGE_API_KEY in "
                "the environment - the key is not part of provider config."
            )
        self._config = config
        self._sleep = sleep
        self._requests = _Pacer(config.requests_per_minute, clock, sleep)
        self._tokens = _Pacer(config.tokens_per_minute, clock, sleep)
        self._count_lock = threading.Lock()
        self._post_count = 0
        self._usage = VoyageUsage(0, 0, 0)
        self._http = httpx.Client(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=config.timeout_seconds,
            transport=transport,
        )

    @property
    def post_count(self) -> int:
        """The count of POSTs this client sent, across all threads."""
        with self._count_lock:
            return self._post_count

    @property
    def usage(self) -> VoyageUsage:
        """The credit use the responses reported to this client."""
        with self._count_lock:
            return self._usage

    @property
    def tokens_per_minute(self) -> int:
        return self._config.tokens_per_minute

    def close(self) -> None:
        """Shut the HTTP connection pool."""
        self._http.close()

    def _add_usage(self, parsed: Mapping[str, object]) -> None:
        # Accounting alone: a response with no such field keeps its
        # rows, because no score reads this value. The smoke tool reports
        # a zero count.
        usage = parsed.get("usage")
        if not isinstance(usage, Mapping):
            return
        with self._count_lock:
            self._usage = VoyageUsage(
                self._usage.image_pixels + _usage_value(usage, "image_pixels"),
                self._usage.text_tokens + _usage_value(usage, "text_tokens"),
                self._usage.total_tokens + _usage_value(usage, "total_tokens"),
            )

    def post_embeddings(self, body: Mapping[str, object],
                        estimated_tokens: int) -> dict[str, object]:
        """POST one body and give back the JSON object.

        Status 429, status 500 and up, and timeouts get retried with
        deterministic exponential backoff, base one second, and a
        numeric Retry-After header wins when it is there. Retries stop
        at the configured limit and then VoyageRequestError raises, or
        VoyageTimeoutError when the last try timed out. A different 4xx
        status raises with no retry. A response that is not a JSON
        object raises VoyageResponseError.
        """
        delay = 0.0
        detail = "no tries made"
        timed_out = False
        tries = self._config.retry_limit + 1
        for attempt_index in range(tries):
            if attempt_index > 0 and delay > 0.0:
                self._sleep(delay)
            self._requests.wait(1)
            self._tokens.wait(estimated_tokens)
            with self._count_lock:
                self._post_count += 1
            try:
                response = self._http.post(_EMBEDDINGS_PATH, json=dict(body))
            except httpx.TimeoutException as error:
                detail = f"timeout: {error!r}"
                timed_out = True
                delay = _BACKOFF_BASE_SECONDS * (2.0 ** attempt_index)
                continue
            except httpx.HTTPError as error:
                raise VoyageRequestError(
                    f"Voyage POST transport failure: {error!r}"
                ) from error
            timed_out = False
            status = response.status_code
            if status == 429 or status >= 500:
                detail = f"status {status}"
                retry_after = _retry_after_seconds(response)
                delay = (retry_after if retry_after is not None
                         else _BACKOFF_BASE_SECONDS * (2.0 ** attempt_index))
                continue
            if status >= 400:
                raise VoyageRequestError(
                    f"Voyage POST got status {status} and is not retried: "
                    f"{response.text[:300]}"
                )
            try:
                parsed = response.json()
            except ValueError as error:
                raise VoyageResponseError(
                    f"Voyage response body is not JSON: {error}"
                ) from error
            if not isinstance(parsed, dict):
                raise VoyageResponseError(
                    "Voyage response JSON is not an object at the top level"
                )
            self._add_usage(parsed)
            return parsed
        error_type = VoyageTimeoutError if timed_out else VoyageRequestError
        raise error_type(
            f"Voyage POST did not succeed after {tries} tries ({detail}). "
            "Examine the account rate limit and the VOYAGE_*_PER_MINUTE "
            "values."
        )
