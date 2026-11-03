"""The positive control for the near-duplicate threshold (spec VE1 section 5).

Spec: docs/specs/voyage-encoder.md section 5. The value 0.95 removed no
image on the working runs, and nothing measured what it catches. This
tool makes duplicate variants of pool images and reports two sets of
cosines in one encoder space: each variant against its source, and pool
pairs. It works with each provider. The owner rules on the threshold
from the numbers. The tool picks no value and changes no config.
"""

import argparse
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

from core.canonical import JsonValue, canonical_json, sha256_hex
from core.types import Vectors
from pool.artifacts import write_json_pretty
from pool.preparation import manifest as mf
from pool.preparation.config import (load_preparation_config,
                                     preparation_config_hash)
from pool.preparation.run import provider_config_hashes, wire_slot
from pool.preparation.stages.outline import photo_canonical
from pool.preparation.types import PreparationTree

# The edits that a duplicate shows in a large image corpus. These
# values make test inputs and enter no scoring path.
_JPEG_QUALITY = 60
_CROP_FRACTION = 0.03
_RESIZE_FRACTION = 0.7
_BRIGHTNESS_FACTOR = 1.1

_QUANTILES: tuple[tuple[str, float], ...] = (
    ("min", 0.0), ("p01", 0.01), ("p05", 0.05), ("p50", 0.50), ("p95", 0.95),
    ("p99", 0.99), ("p999", 0.999), ("max", 1.0))

VARIANT_NAMES: tuple[str, ...] = ("jpeg", "crop", "resize", "brightness")


@dataclass(frozen=True, slots=True)
class SpaceReport:
    """The cosine sets of one encoder space.

    variants maps a variant name to the quantiles of its cosines against
    the source images. pool_pairs holds the quantiles across the source
    pairs. margin is the lowest variant cosine less the highest pool
    pair: a positive value means that one threshold separates the two.
    """

    encoder_hash: str
    source_count: int
    variants: Mapping[str, Mapping[str, float]]
    pool_pairs: Mapping[str, float]
    margin: float


def _png_rgb(photo: bytes) -> Image.Image:
    with Image.open(BytesIO(photo)) as image:
        image.load()
        return image.convert("RGB")


def _encoded(image: Image.Image, encoding: str = "PNG", **options: int) -> bytes:
    buffer = BytesIO()
    image.save(buffer, encoding, **options)
    return buffer.getvalue()


def duplicate_variants(photo: bytes) -> dict[str, bytes]:
    """The four variants of one photograph, as image bytes."""
    image = _png_rgb(photo)
    width, height = image.size
    cut_x = max(1, round(width * _CROP_FRACTION))
    cut_y = max(1, round(height * _CROP_FRACTION))
    smaller = (max(1, round(width * _RESIZE_FRACTION)),
               max(1, round(height * _RESIZE_FRACTION)))
    return {
        "jpeg": _encoded(image, "JPEG", quality=_JPEG_QUALITY),
        "crop": _encoded(image.crop((cut_x, cut_y, width - cut_x, height - cut_y))),
        "resize": _encoded(image.resize(smaller, Image.Resampling.LANCZOS)),
        "brightness": _encoded(ImageEnhance.Brightness(image).enhance(_BRIGHTNESS_FACTOR)),
    }


def quantiles(values: np.ndarray) -> dict[str, float]:
    """The named quantiles of one value set, as plain floats."""
    return {name: round(float(np.quantile(values, fraction)), 6)
            for name, fraction in _QUANTILES}


def space_report(encoder_hash: str, sources: Vectors,
                 variants: Mapping[str, Vectors]) -> SpaceReport:
    """Compare unit rows: sources (S, d) and each variant set (S, d)."""
    count = sources.shape[0]
    if count < 2:
        raise ValueError(f"the report needs two sources or more, got {count}")
    variant_cosines = {
        name: np.sum(rows * sources, axis=1)  # (S,)
        for name, rows in variants.items()
    }
    similarity = sources @ sources.T               # (S, S)
    pairs = similarity[np.triu_indices(count, 1)]  # (S * (S - 1) / 2,)
    lowest = min(float(values.min()) for values in variant_cosines.values())
    return SpaceReport(
        encoder_hash=encoder_hash,
        source_count=count,
        variants={name: quantiles(values)
                  for name, values in variant_cosines.items()},
        pool_pairs=quantiles(pairs),
        margin=round(lowest - float(pairs.max()), 6),
    )


def calibrate_space(
    encoder_hash: str,
    encode: Callable[[Sequence[bytes]], Vectors],
    photos: Sequence[bytes],
    canvas_px: int,
) -> SpaceReport:
    """Encode the sources and the variants through the canonical render.

    A variant goes through the same photo_canonical rule as a pool
    image, thus the cosines describe the path the threshold reads.
    """
    sources = encode([photo_canonical(photo, canvas_px) for photo in photos])
    variants_of = [duplicate_variants(photo) for photo in photos]
    rows = {
        name: encode([photo_canonical(group[name], canvas_px)
                      for group in variants_of])
        for name in VARIANT_NAMES
    }
    return space_report(encoder_hash, sources, rows)


def sampled_ids(image_ids: Sequence[str], sample: int, seed: int) -> list[str]:
    """A seeded sample of image ids, in ascending sequence."""
    ordered = sorted(image_ids)
    return sorted(random.Random(seed).sample(ordered, min(sample, len(ordered))))


def _preparation_tree(config, data_root: Path) -> PreparationTree:
    record = mf.parse_release_record(Path(config.input.release_record))
    return PreparationTree(
        data_root=data_root,
        pool_version_id=record.pool_version_id,
        preparation_config_hash=preparation_config_hash(
            config, provider_config_hashes(config)),
        pool_label=record.label,
    )


def _report_document(report: SpaceReport) -> dict[str, JsonValue]:
    return {
        "encoder_hash": report.encoder_hash,
        "source_count": report.source_count,
        "variants": {name: dict(values) for name, values in report.variants.items()},
        "pool_pairs": dict(report.pool_pairs),
        "margin": report.margin,
    }


def format_report(name: str, report: SpaceReport) -> str:
    lines = [f"{name}  ({report.source_count} sources, encoder "
             f"{report.encoder_hash[:8]})"]
    for label, values in [*report.variants.items(), ("pool pairs", report.pool_pairs)]:
        lines.append(f"  {label:<11} " + "  ".join(
            f"{key} {value:.3f}" for key, value in values.items()))
    lines.append(f"  margin      {report.margin:+.3f}  "
                 "(lowest variant less highest pool pair)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.neardup_calibration")
    parser.add_argument("--config", required=True, type=Path,
                        help="a preparation config with a complete p00 stage")
    parser.add_argument("--curation-config", type=Path,
                        help="adds the s06 space, with the encoder of this config")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--data-root", default="data", type=Path)
    parser.add_argument("--records-root", default="validation/records", type=Path)
    arguments = parser.parse_args(argv)

    config = load_preparation_config(arguments.config)
    tree = _preparation_tree(config, arguments.data_root)
    rows = mf.read_jsonl(mf.stage_dir(tree, "p00-intake") / "records.jsonl")
    ids = sampled_ids([str(row["image_id"]) for row in rows],
                      arguments.sample, arguments.seed)
    photos = [mf.load_image_bytes(arguments.data_root, image_id) for image_id in ids]

    image_encoder = wire_slot("image_encoder", config, arguments.data_root)
    spaces = {"p08": calibrate_space(
        image_encoder.config_hash, image_encoder.encode_images, photos,
        config.linedraw.canvas_px)}
    if arguments.curation_config is not None:
        from pool.curation.config import load_curation_config
        from pool.curation.run import wire_slot as wire_curation_slot

        curation = load_curation_config(arguments.curation_config)
        encoder = wire_curation_slot("encoder", curation, arguments.data_root)
        canvas_px = curation.providers.encoder.input_canvas_px
        if canvas_px is None:
            raise ValueError("the curation encoder names no input_canvas_px")
        spaces["s06"] = calibrate_space(
            encoder.config_hash, encoder.encode_images, photos, canvas_px)

    document: dict[str, JsonValue] = {
        "harness": "neardup-calibration",
        "date": date.today().isoformat(),
        "config_path": str(arguments.config),
        "seed": arguments.seed,
        "sample": len(ids),
        "threshold_in_config": config.neardup.similarity_threshold,
        "spaces": {name: _report_document(report) for name, report in spaces.items()},
    }
    digest = sha256_hex(canonical_json(
        {"config": str(arguments.config), "seed": arguments.seed, "ids": ids,
         "hashes": {name: report.encoder_hash for name, report in spaces.items()}}))
    path = arguments.records_root / (
        f"neardup-calibration-{config.release.tag}-{digest[:8]}.json")
    write_json_pretty(path, document)
    for name, report in spaces.items():
        print(format_report(name, report))
    print(f"config threshold {config.neardup.similarity_threshold}")
    print(f"record {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
