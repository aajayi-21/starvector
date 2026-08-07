"""s08 review stage: seeded sample selection and the contact sheet.

Spec: docs/specs/pool-curation.md section 10, s08. Pure functions
only - the runner reads and writes files. The sample comes from
review_seed, and the contact sheet is one self-contained HTML page.
"""

import html
from collections.abc import Sequence
from io import BytesIO
from typing import NamedTuple

import numpy as np
from PIL import Image


class ReviewEntry(NamedTuple):
    """One contact sheet cell: identity, caption, and thumbnail."""

    image_id: str
    caption: str
    thumbnail_png_base64: str   # base64 text of the PNG thumbnail bytes


def select_review_sample(
    image_ids: Sequence[str], sample_size: int, review_seed: int
) -> tuple[str, ...]:
    """Select the seeded review sample from sorted image_id values.

    The input must be in ascending sequence - the seeded selection is
    deterministic only for a fixed input sequence. The output has
    min(sample_size, n) different ids, in ascending sequence.
    """
    ids = list(image_ids)
    if ids != sorted(ids):
        raise ValueError("image_ids must be sorted ascending")
    rng = np.random.default_rng(review_seed)
    size = min(sample_size, len(ids))
    indices = rng.choice(len(ids), size=size, replace=False)
    return tuple(sorted(ids[int(index)] for index in indices))


def thumbnail_png(image_bytes: bytes, max_side: int) -> bytes:
    """Decode one image and make a small PNG thumbnail.

    Pillow converts the image to RGB, then scales it down with LANCZOS
    resampling to fit max_side on the larger dimension. The output is
    PNG bytes with no metadata. Equal input gives equal output.
    """
    buffer = BytesIO()
    with Image.open(BytesIO(image_bytes)) as image:
        converted = image.convert("RGB")
        converted.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        converted.save(buffer, format="PNG")
    return buffer.getvalue()


_STYLE = (
    "body{font-family:system-ui,sans-serif;margin:1.5rem;background:#fafafa;color:#222}"
    "h1{font-size:1.3rem}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1rem}"
    ".cell{background:#fff;border:1px solid #ddd;border-radius:6px;padding:.75rem;margin:0}"
    ".cell img{max-width:100%;height:auto;display:block;margin:0 auto}"
    ".cell figcaption{font-size:.85rem;margin-top:.5rem}"
    ".cell code{display:block;font-family:monospace;font-size:.7rem;"
    "margin-top:.5rem;word-break:break-all;color:#555}"
)


def contact_sheet_html(entries: Sequence[ReviewEntry], label: str) -> str:
    """Build the self-contained contact sheet HTML document.

    Inline CSS only, with each thumbnail embedded as a data URI - no
    external hosts. Each cell shows the thumbnail, the caption as
    plain text, and the image_id in monospace. Equal input gives
    equal output.
    """
    title = html.escape(label)
    cells = "".join(
        '<figure class="cell">'
        f'<img src="data:image/png;base64,{entry.thumbnail_png_base64}" '
        f'alt="{html.escape(entry.image_id)}">'
        f"<figcaption>{html.escape(entry.caption)}</figcaption>"
        f"<code>{html.escape(entry.image_id)}</code>"
        "</figure>"
        for entry in entries
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{title}</title>\n"
        f"<style>{_STYLE}</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{title}</h1>\n"
        f'<main class="grid">{cells}</main>\n'
        "</body>\n"
        "</html>\n"
    )
