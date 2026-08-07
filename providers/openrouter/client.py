"""One synchronous HTTP client for the OpenRouter chat API.

Spec: docs/specs/pool-curation.md section 8a. Concurrency, rate
limits, retries, and backoff live in this client - callers see the
batched slot protocols only. The slot providers share one client, and
the client counts each POST it sends.
"""

import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

import httpx

from providers.openrouter.errors import OpenRouterRequestError, OpenRouterResponseError

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_BACKOFF_BASE_SECONDS = 1.0


class OpenRouterClientConfig(NamedTuple):
    """Transport settings for one OpenRouterClient.

    The base_url field gets the standard OpenRouter API root as its
    default at construction.
    """

    max_concurrency: int
    requests_per_second: float
    timeout_seconds: float
    retry_limit: int
    base_url: str = DEFAULT_BASE_URL


class _TokenBucket:
    """Thread-safe token bucket on the monotonic clock."""

    def __init__(self, rate: float, capacity: float) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Wait until one token is available, then use it."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            time.sleep(wait)


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


class OpenRouterClient:
    """Shared POST transport with a rate limit, retries, and a counter.

    The API key comes from the environment at wiring time and is not
    part of provider configuration (spec section 8a). Tests inject an
    httpx.MockTransport.
    """

    def __init__(
        self,
        config: OpenRouterClientConfig,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise OpenRouterRequestError(
                "OpenRouter API key is missing or empty. Set OPENROUTER_API_KEY "
                "in the environment - the key is not part of provider config."
            )
        self._config = config
        self._bucket = _TokenBucket(
            rate=config.requests_per_second,
            capacity=float(max(1, config.max_concurrency)),
        )
        self._post_count = 0
        self._count_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=config.max_concurrency)
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

    def close(self) -> None:
        """Shut the thread pool and the HTTP connection pool."""
        self._executor.shutdown(wait=True)
        self._http.close()

    def post_chat(self, body: Mapping[str, object]) -> dict[str, object]:
        """POST one chat-completions body and give back the JSON object.

        Status 429, status 500 and up, and timeouts get retried with
        deterministic exponential backoff, base one second, and a
        numeric Retry-After header wins when it is there. Retries stop
        at the configured limit and then OpenRouterRequestError raises.
        A different 4xx status raises with no retry. A response that is
        not a JSON object raises OpenRouterResponseError.
        """
        delay = 0.0
        detail = "no tries made"
        tries = self._config.retry_limit + 1
        for attempt_index in range(tries):
            if attempt_index > 0 and delay > 0.0:
                time.sleep(delay)
            self._bucket.acquire()
            with self._count_lock:
                self._post_count += 1
            try:
                response = self._http.post("/chat/completions", json=dict(body))
            except httpx.TimeoutException as error:
                detail = f"timeout: {error!r}"
                delay = _BACKOFF_BASE_SECONDS * (2.0 ** attempt_index)
                continue
            except httpx.HTTPError as error:
                raise OpenRouterRequestError(
                    f"OpenRouter POST transport failure: {error!r}"
                ) from error
            status = response.status_code
            if status == 429 or status >= 500:
                detail = f"status {status}"
                retry_after = _retry_after_seconds(response)
                if retry_after is not None:
                    delay = retry_after
                else:
                    delay = _BACKOFF_BASE_SECONDS * (2.0 ** attempt_index)
                continue
            if status >= 400:
                raise OpenRouterRequestError(
                    f"OpenRouter POST got status {status} and is not retried: "
                    f"{response.text[:300]}"
                )
            try:
                parsed = response.json()
            except ValueError as error:
                raise OpenRouterResponseError(
                    f"OpenRouter response body is not JSON: {error}"
                ) from error
            if not isinstance(parsed, dict):
                raise OpenRouterResponseError(
                    "OpenRouter response JSON is not an object at the top level"
                )
            return parsed
        raise OpenRouterRequestError(
            f"OpenRouter POST did not succeed after {tries} tries ({detail}). "
            "Examine the rate limit and the retry limit in the client config."
        )

    def map_requests(self, bodies: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
        """POST all bodies through the shared thread pool.

        The output rows are index-aligned with bodies. Concurrency is
        the configured maximum, and the token bucket applies across
        the threads.
        """
        return list(self._executor.map(self.post_chat, bodies))
