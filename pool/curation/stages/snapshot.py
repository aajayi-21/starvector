"""Pure sampling rules for stage s00.

Spec: docs/specs/pool-curation.md section 10, s00. The sampling hash is
a pure function of the salt and the source key. Thus the corpus
enumeration sequence has no effect on the kept set.
"""

from collections.abc import Iterable

from core.canonical import sha256_hex

_HASH_SPACE = 2.0**64


def sampling_hash(sample_salt: str, source_key: str) -> int:
    """The 64-bit sampling quantity for one source key.

    The output is the value of the first 16 hex digits of the SHA-256
    digest of the salt plus the key, encoded as UTF-8.
    """
    return int(sha256_hex(sample_salt + source_key)[:16], 16)


def keep_in_sample(sample_salt: str, source_key: str, sample_rate: float) -> bool:
    """The s00 sampling rule.

    A record stays in the sample when its sampling hash, divided by
    2**64, is less than the sample rate. A rate of 1.0 keeps all
    records.
    """
    return sampling_hash(sample_salt, source_key) / _HASH_SPACE < sample_rate


def fetch_order(source_keys: Iterable[str], sample_salt: str) -> tuple[str, ...]:
    """Sort source keys for the s02 fetch, ascending by (hash, key).

    Stage s02 issues fetches in this sequence. The budget cut is free
    of selection bias because s00 sampled with the same quantity.
    """
    return tuple(
        sorted(source_keys, key=lambda key: (sampling_hash(sample_salt, key), key))
    )
