"""Deterministic fake VLM describer for tests.

Fills the VlmDescriber slot of docs/specs/pool-preparation.md section 8.
The fake_elements PNG chunk scripts the full seven-field response. This
fake is the test instrument for boundary fixtures, thus it does not
apply the D2 field-count contract — a scripted count above the
contract comes through unchanged.
"""

import json
from collections.abc import Sequence

from core.canonical import canonical_json, sha256_hex
from providers.fake.chunks import read_fake_chunks
from providers.protocols import ElementResponse

# The R2 schema fields, split by shape. The names are the frozen field
# names of ElementResponse (providers/protocols.py).
_TUPLE_FIELDS = ("objects", "materials", "colors", "shapes", "ambience")
_STRING_FIELDS = ("scale", "setting")


def _parse_response(text: str) -> ElementResponse:
    """One ElementResponse parsed from the scripted chunk text.

    The chunk text must be a JSON object with the seven R2 schema
    fields and no other keys. Text that does not parse, a missing or
    unknown key, or a field with an incorrect shape raises ValueError.
    Field counts are not checked — boundary fixtures script counts
    above the contract on purpose.
    """
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError(f"fake_elements chunk is not a JSON object: {text!r}")
    expected_keys = set(_TUPLE_FIELDS) | set(_STRING_FIELDS)
    if set(document) != expected_keys:
        raise ValueError(
            f"fake_elements keys {sorted(document)} do not agree with the "
            f"R2 schema fields {sorted(expected_keys)}"
        )
    fields: dict[str, tuple[str, ...] | str] = {}
    for field_name in _TUPLE_FIELDS:
        value = document[field_name]
        if not isinstance(value, list) or not all(
            isinstance(entry, str) for entry in value
        ):
            raise ValueError(f"fake_elements field {field_name!r} is not a string array")
        fields[field_name] = tuple(value)
    for field_name in _STRING_FIELDS:
        value = document[field_name]
        if not isinstance(value, str):
            raise ValueError(f"fake_elements field {field_name!r} is not a string")
        fields[field_name] = value
    return ElementResponse(**fields)  # type: ignore[arg-type]


class FakeVlmDescriber:
    """Describer that reads the scripted response from the fake_elements chunk.

    A fake_describer_error chunk scripts a provider error: the describer
    raises ValueError with the chunk text, which the R13 stop-the-run
    tests use.
    """

    @property
    def config_hash(self) -> str:
        """Stable hash of the fake describer parameters."""
        return sha256_hex(canonical_json({"provider": "fake-describer"}))

    def describe_images(self, images: Sequence[bytes]) -> list[ElementResponse]:
        """One parsed ElementResponse for each image, index-aligned.

        A missing fake_elements chunk — which includes each image format
        without text chunks, for example JPEG — raises ValueError.
        """
        responses: list[ElementResponse] = []
        for image_bytes in images:
            chunks = read_fake_chunks(image_bytes)
            error_text = chunks.get("fake_describer_error")
            if error_text is not None:
                raise ValueError(error_text)
            text = chunks.get("fake_elements")
            if text is None:
                raise ValueError("fake_elements chunk is missing")
            responses.append(_parse_response(text))
        return responses
