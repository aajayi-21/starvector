"""Stage p01 validation checks. The describer owns response parsing.

Spec: docs/specs/pool-preparation.md section 10, stage p01. The
provider parses and validates each response at its boundary (R14).
This module only makes sure the image_id sequence and the provider
output align.
"""

from collections.abc import Sequence

from pool.preparation.types import ElementResponse


def elements_align(
    image_ids: Sequence[str], responses: Sequence[ElementResponse]
) -> tuple[tuple[str, ElementResponse], ...]:
    """Pair each image_id with its response, index-aligned.

    Raises ValueError when the counts do not agree - a misaligned
    provider output must not become an artifact (R14).
    """
    if len(responses) != len(image_ids):
        raise ValueError(
            f"describer gave {len(responses)} response(s) for {len(image_ids)} image(s)"
        )
    return tuple(zip(image_ids, responses))
