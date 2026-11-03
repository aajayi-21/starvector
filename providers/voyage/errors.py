"""The error types of the Voyage provider (spec VE1 section 3)."""


class VoyageRequestError(RuntimeError):
    """A POST did not get a usable answer: transport, status, or retries."""


class VoyageTimeoutError(VoyageRequestError):
    """Each try of one POST timed out. A batch can split and go again."""


class VoyageResponseError(ValueError):
    """An answer or a cache entry does not hold the expected values (R14)."""
