"""Stage p05 bookkeeping rules. The drawing work is in the provider.

Spec: docs/specs/pool-preparation.md section 10, stage p05.
Architecture rule R7 makes binarize, short-segment removal, and the
canonical re-render internal to the LineDrawer provider. This module
only checks bytes and builds cache keys.
"""

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def linedraw_check_png(image_id: str, drawing: bytes) -> None:
    """Make sure one provider output starts with the PNG signature.

    The LineDrawer contract is canonical rendered PNG bytes. For
    other bytes the check raises ValueError with the image_id named
    (R14).
    """
    if not drawing.startswith(PNG_SIGNATURE):
        raise ValueError(f"line drawing for {image_id} is not a PNG")


def linedraw_key(line_drawer_hash: str, image_id: str) -> str:
    """The stable line_drawing_key of one stored drawing.

    The key mirrors the image-level cache layout of spec section 11:
    the first 8 hex digits of the LineDrawer config hash, the first 2
    hex digits of the image_id, then the file name.
    """
    return f"{line_drawer_hash[:8]}/{image_id[:2]}/{image_id}.png"
