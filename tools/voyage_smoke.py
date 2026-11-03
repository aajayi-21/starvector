"""A short live check of the Voyage slot, for the owner to run.

Spec: docs/specs/voyage-encoder.md sections 3 and 8. It makes four
POSTs, reports the numbers, and stores the canary vector, which finds a
silent change of the model on the next run. It uses a temporary cache,
thus each run goes to the endpoint and no pool cache changes. The key
comes from VOYAGE_API_KEY and is not printed.
"""

import argparse
import json
import sys
import tempfile
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image, ImageDraw

from providers.voyage.client import VoyageClient
from providers.voyage.embeddings import (VoyageImageEncoder, VoyageSlotConfig,
                                         VoyageTextEncoder)
from providers.voyage.errors import VoyageRequestError, VoyageResponseError
from providers.voyage.wiring import client_from_environment

DEFAULT_MODEL = "voyage-multimodal-3.5"
DEFAULT_DIMENSION = 1024
DEFAULT_CANARY = Path("validation/records/voyage-canary.json")
_INSTRUCTION = "Represent this rough freehand line sketch."
_CANARY_TEXT = "a red door in a stone wall"


class SmokeReport(NamedTuple):
    """The numbers of one smoke run. Each cosine is a dot of unit rows."""

    dimension: int
    repeat_cosine: float
    instruction_cosine: float
    canary_cosine: float | None
    posts: int
    image_pixels: int
    text_tokens: int


def canary_image() -> bytes:
    """A fixed drawing, 64 x 64 pixels, in PNG bytes."""
    image = Image.new("RGB", (64, 64), "white")
    drawer = ImageDraw.Draw(image)
    drawer.rectangle((12, 12, 52, 52), outline="black", width=2)
    drawer.line((12, 52, 52, 12), fill="black", width=2)
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def _unit_row_check(row: np.ndarray, dimension: int) -> None:
    if row.shape != (dimension,):
        raise VoyageResponseError(
            f"a row has shape {row.shape}, the config pins ({dimension},)")
    if abs(float(np.linalg.norm(row)) - 1.0) > 1e-5:
        raise VoyageResponseError("a row is not unit-norm after the provider")


def run_smoke(client: VoyageClient, model: str, dimension: int,
              canary_path: Path) -> SmokeReport:
    """Make the POSTs, compare the rows, and write a new canary if none.

    Each encoder gets its own temporary cache, thus the second plain
    encode is a second POST and not a cache read.
    """
    image = canary_image()

    def encoder(slot: str, instruction: str | None, root: str) -> VoyageImageEncoder:
        return VoyageImageEncoder(
            VoyageSlotConfig(slot, model, dimension, instruction), client,
            Path(root))

    with tempfile.TemporaryDirectory() as first, \
            tempfile.TemporaryDirectory() as second:
        plain = encoder("smoke", None, first).encode_images([image])[0]
        repeat = encoder("smoke", None, second).encode_images([image])[0]
        joint = encoder("smoke-instruction", _INSTRUCTION,
                        first).encode_images([image])[0]
        text = VoyageTextEncoder(
            VoyageSlotConfig("smoke-text", model, dimension), client,
            Path(first)).encode_texts([_CANARY_TEXT])[0]
    for row in (plain, repeat, joint, text):
        _unit_row_check(row, dimension)

    canary_cosine: float | None = None
    if canary_path.is_file():
        stored = json.loads(canary_path.read_text(encoding="utf-8"))
        if stored["model"] == model and stored["dimension"] == dimension:
            canary_cosine = float(
                np.dot(np.asarray(stored["image_row"], dtype=np.float32), plain))
    else:
        canary_path.parent.mkdir(parents=True, exist_ok=True)
        canary_path.write_text(json.dumps(
            {"model": model, "dimension": dimension,
             "image_row": [float(value) for value in plain]}) + "\n",
            encoding="utf-8")
    usage = client.usage
    return SmokeReport(
        dimension=dimension,
        repeat_cosine=float(np.dot(plain, repeat)),
        instruction_cosine=float(np.dot(plain, joint)),
        canary_cosine=canary_cosine,
        posts=client.post_count,
        image_pixels=usage.image_pixels,
        text_tokens=usage.text_tokens,
    )


def format_report(report: SmokeReport) -> str:
    canary = ("stored a new canary" if report.canary_cosine is None
              else f"{report.canary_cosine:.6f} against the stored canary")
    # A zero means the responses held no credit field, thus the credit
    # count of the pool runs reads zero too.
    usage_note = "" if report.image_pixels > 0 else \
        "  (no usage in the responses)"
    return "\n".join((
        f"dimension            {report.dimension}",
        f"repeat cosine        {report.repeat_cosine:.6f}",
        f"instruction cosine   {report.instruction_cosine:.6f}"
        "  (1.0 means that the endpoint ignores the instruction)",
        f"canary               {canary}",
        f"posts                {report.posts}",
        f"image pixels         {report.image_pixels}{usage_note}",
        f"text tokens          {report.text_tokens}",
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.voyage_smoke")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dimension", type=int, default=DEFAULT_DIMENSION)
    parser.add_argument("--canary", type=Path, default=DEFAULT_CANARY)
    arguments = parser.parse_args(argv)
    try:
        report = run_smoke(client_from_environment(), arguments.model,
                           arguments.dimension, arguments.canary)
    except (VoyageRequestError, VoyageResponseError) as error:
        print(f"smoke did not complete: {error}", file=sys.stderr)
        return 1
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
