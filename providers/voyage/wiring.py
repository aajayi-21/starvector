"""The one module where a Voyage encoder gets its key and its limits.

Spec: docs/specs/voyage-encoder.md section 3. The pool, scoring, and
validation wiring sites use these functions. The key and the limits for
each minute come from the environment, because they belong to the
account, and no hash reads them.
"""

import os
from pathlib import Path

from providers.voyage.client import VoyageClient, VoyageClientConfig
from providers.voyage.embeddings import (VoyageImageEncoder, VoyageSlotConfig,
                                         VoyageTextEncoder)

# The published first tier of this model (spec VE1 section 3).
_DEFAULT_REQUESTS_PER_MINUTE = 2_000
_DEFAULT_TOKENS_PER_MINUTE = 2_000_000
_TIMEOUT_SECONDS = 120.0
# Six backoff waits sum to 63 seconds, which clears a limit for each minute.
_RETRY_LIMIT = 6


def _positive_environment_int(name: str, default: int) -> int:
    text = os.environ.get(name)
    if text is None:
        return default
    try:
        value = int(text)
    except ValueError as error:
        raise ValueError(f"{name} is not a whole number: {text!r}") from error
    if value < 1:
        raise ValueError(f"{name} must be 1 or more: {value}")
    return value


def client_from_environment() -> VoyageClient:
    """A client with the environment's key and account limits."""
    return VoyageClient(
        VoyageClientConfig(
            requests_per_minute=_positive_environment_int(
                "VOYAGE_REQUESTS_PER_MINUTE", _DEFAULT_REQUESTS_PER_MINUTE),
            tokens_per_minute=_positive_environment_int(
                "VOYAGE_TOKENS_PER_MINUTE", _DEFAULT_TOKENS_PER_MINUTE),
            timeout_seconds=_TIMEOUT_SECONDS,
            retry_limit=_RETRY_LIMIT,
        ),
        api_key=os.environ.get("VOYAGE_API_KEY", ""),
    )


def image_encoder(slot_config: VoyageSlotConfig,
                  data_root: Path) -> VoyageImageEncoder:
    """An image or sketch encoder, with its cache below the data root."""
    return VoyageImageEncoder(slot_config, client_from_environment(),
                              data_root / "cache" / "voyage")


def text_encoder(slot_config: VoyageSlotConfig,
                 data_root: Path) -> VoyageTextEncoder:
    """A text encoder, with its cache below the data root."""
    return VoyageTextEncoder(slot_config, client_from_environment(),
                             data_root / "cache" / "voyage")
