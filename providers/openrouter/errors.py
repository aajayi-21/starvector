"""Error types for the OpenRouter providers.

Spec: docs/specs/pool-curation.md section 8a and R14. Transport
problems, and retries that do not succeed, use OpenRouterRequestError.
A response that arrived but does not parse or does not validate uses
OpenRouterResponseError. No silent fallbacks - a bad response raises
and does not become a default value.
"""

from providers.protocols import InputRefused


class OpenRouterRequestError(RuntimeError):
    """An HTTP POST to OpenRouter could not get a good response."""


class OpenRouterInputRefused(OpenRouterRequestError, InputRefused):
    """OpenRouter refused the content of one POST (spec CR1 section 5).

    A status of 400, 413, or 422, in the answer or in an error body. A
    401, 402, 403, or 404 is a key, a balance, or a model that is
    missing, which is the configuration and not the input, thus those
    stay OpenRouterRequestError.
    """


class OpenRouterTimeoutError(OpenRouterRequestError):
    """Each try of one POST ran out of time.

    Its own type, thus a caller that can shrink the POST body -
    the embeddings batcher - can tell a too-slow batch from a
    failure that a smaller body cannot repair.
    """


class OpenRouterResponseError(ValueError):
    """A response or a cache entry arrived but did not validate."""
