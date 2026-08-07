"""PNG text chunk access for the fake providers.

The fake corpus stores scripted values as PNG tEXt chunks. The fake
providers read them back with this helper.
"""

from io import BytesIO

from PIL import Image


def read_fake_chunks(image_bytes: bytes) -> dict[str, str]:
    """Read the PNG text chunks of one image.

    The output maps chunk keys to chunk values. Missing chunks have no
    entry in the output.
    """
    with Image.open(BytesIO(image_bytes)) as image:
        return dict(image.text)
