"""PNG text chunk access for the fake providers.

The fake corpus stores scripted values as PNG tEXt chunks. The fake
providers read them back with this helper.
"""

from io import BytesIO

from PIL import Image


def read_fake_chunks(image_bytes: bytes) -> dict[str, str]:
    """Read the PNG text chunks of one image.

    The output maps chunk keys to chunk values. Missing chunks have no
    entry in the output. An image format without text chunks, for
    example JPEG, gives an empty output. The fake encoder then uses its
    unscripted rule (a vector seeded from the bytes). For the fake
    classifier and estimators an empty output is a missing chunk, which
    causes their missing-chunk ValueError.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        text = getattr(image, "text", None)
        if text is None:
            return {}
        return dict(text)
