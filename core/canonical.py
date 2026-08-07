"""Canonical JSON and hashing helpers.

Spec: docs/specs/pool-curation.md section 14. Each artifact hash and each
stored JSON file in the curation pipeline goes through these functions,
and thus two equal runs give byte-for-byte equal output.
"""

import hashlib
import json
import math

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


def canonical_float(x: float) -> float:
    """Validate and normalize one float for canonical JSON.

    Rejects NaN and infinities. Normalizes negative zero to zero.
    Callers convert numpy scalars through this function before
    serialization.
    """
    value = float(x)
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"non-finite float is not canonical: {x!r}")
    if value == 0.0:
        return 0.0
    return value


def quantize_measured(x: float) -> float:
    """Quantize one measured value before it enters an artifact.

    Spec section 14: measured values are rounded to six decimal places.
    The shortest-roundtrip float repr then gives stable text.
    """
    return canonical_float(round(float(x), 6))


def canonical_json(value: JsonValue) -> str:
    """Compact canonical text: sorted keys, no spaces, UTF-8 as-is.

    This text is the hash input and the JSONL row. Hash inputs use the
    string without a line ending. File rows append one newline.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def canonical_json_pretty(value: JsonValue) -> str:
    """Pretty canonical text for meta files and release records."""
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)


def sha256_hex(data: bytes | str) -> str:
    """SHA-256 hex digest. A str input is encoded as UTF-8 first."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
