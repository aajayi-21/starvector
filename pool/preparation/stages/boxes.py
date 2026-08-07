"""Stage p07 box validation rules. Pure checks on provider output.

Spec: docs/specs/pool-preparation.md section 10, stage p07, and
decision D10. Architecture rule R11 defines the artifact. None
records "not located" and is a permitted answer, not an error.
"""

from collections.abc import Mapping, Sequence

from pool.preparation.types import Box


def boxes_validate(
    image_id: str, elements: Sequence[str], response: Mapping[str, Box | None]
) -> None:
    """Check one box response against its queried element list.

    The response keys must equal the queried element set. Each box
    has values in [0, 1] with x_min below x_max and y_min below
    y_max. None is a permitted answer for each element. An empty
    query with an empty response is complete. A bad response raises
    ValueError with the image_id named (R14).
    """
    expected = set(elements)
    received = set(response)
    if received != expected:
        missing = sorted(expected - received)
        extra = sorted(received - expected)
        raise ValueError(
            f"boxes for {image_id}: keys do not agree with the queried element "
            f"list (missing {missing}, extra {extra})"
        )
    for element in sorted(expected):
        box = response[element]
        if box is None:
            continue
        values = (box.x_min, box.y_min, box.x_max, box.y_max)
        if not all(0.0 <= value <= 1.0 for value in values):
            raise ValueError(f"boxes for {image_id}: {element!r} has a value not in [0, 1]")
        if not (box.x_min < box.x_max and box.y_min < box.y_max):
            raise ValueError(f"boxes for {image_id}: {element!r} minimum is not below maximum")
