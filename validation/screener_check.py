"""Show what the one-POST screener rejects, for the owner's ruling.

Spec: docs/specs/production-pool.md section 5a. The person rule and the
new labels are wording in one instruction, and only the images can show
if the wording is correct. This tool runs a curation config's screener
on one stage manifest, and writes one HTML sheet with each image in the
group of its first rejection. It changes no config and no pool.
"""

import argparse
import base64
import html
import json
from collections import Counter
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path

from PIL import Image

from core.canonical import sha256_hex
from pool.artifacts import load_image_bytes
from pool.curation.config import CurationConfig, load_curation_config
from pool.curation.run import wire_slot
from pool.curation.stages.classify import (NO_WINNER_REASON, reason_for_label,
                                           winning_label)

_THUMBNAIL_PX = 256
KEPT = "kept"


def screen_group(text: float, label: str | None, object_fraction: float,
                 person_main: float, config: CurationConfig) -> str:
    """The first rule that rejects one image, in stage sequence.

    label is the one winner of the label row, or None for a row with no
    winner (the s04 rule).
    """
    if text > config.text.max_text_coverage:
        return "text-coverage"
    if label is None:
        return NO_WINNER_REASON
    if label != config.classify.keep_label:
        return reason_for_label(label)
    if object_fraction <= config.objectsize.min_object_fraction:
        return "object-size"
    if config.person is not None and person_main > 0.0:
        return "person-focus"
    return KEPT


def screen_groups(image_bytes: Sequence[bytes], provider: object,
                  config: CurationConfig) -> list[str]:
    """One group for each image, index-aligned."""
    labels = config.classify.labels
    texts = provider.estimate_text_coverage(image_bytes)
    classes = provider.classify(image_bytes, labels)
    objects = provider.estimate_salient_object_fraction(image_bytes)
    people = provider.person_is_main_subject(image_bytes)
    return [
        screen_group(float(texts[i]), winning_label(classes[i], labels),
                     float(objects[i]), float(people[i]), config)
        for i in range(len(image_bytes))
    ]


def _thumbnail_uri(image: bytes) -> str:
    with Image.open(BytesIO(image)) as opened:
        small = opened.convert("RGB")
    small.thumbnail((_THUMBNAIL_PX, _THUMBNAIL_PX))
    buffer = BytesIO()
    small.save(buffer, "JPEG", quality=80)
    return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode()}"


def sheet_html(rows: Sequence[tuple[str, str, bytes]]) -> str:
    """The page: one section for each group, largest rejection first."""
    groups: dict[str, list[tuple[str, bytes]]] = {}
    for image_id, group, image in rows:
        groups.setdefault(group, []).append((image_id, image))
    sections = []
    for group in sorted(groups, key=lambda name: (name == KEPT, -len(groups[name]))):
        images = "".join(
            f'<img src="{_thumbnail_uri(image)}" title="{html.escape(image_id)}" '
            'style="height:160px;margin:2px">'
            for image_id, image in groups[group])
        sections.append(f"<h2>{html.escape(group)} ({len(groups[group])})</h2>"
                        f"<div>{images}</div>")
    return ("<!doctype html><meta charset=utf-8><title>Screener check</title>"
            "<body style='font-family:sans-serif'>" + "".join(sections))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.screener_check")
    parser.add_argument("--config", required=True, type=Path,
                        help="a curation config with a screener section")
    parser.add_argument("--manifest", required=True, type=Path,
                        help="a stage manifest.jsonl with the images to screen")
    parser.add_argument("--data-root", default="data", type=Path)
    arguments = parser.parse_args(argv)
    config = load_curation_config(arguments.config)
    if config.providers.screener is None:
        parser.error("the config has no screener section")
    with arguments.manifest.open(encoding="utf-8") as lines:
        ids = [str(json.loads(line)["image_id"]) for line in lines if line.strip()]
    images = [load_image_bytes(arguments.data_root, image_id) for image_id in ids]
    provider = wire_slot("text_coverage", config, arguments.data_root)
    groups = screen_groups(images, provider, config)
    digest = sha256_hex(provider.config_hash + str(arguments.manifest))[:8]
    path = arguments.data_root / "validation" / "screener-check" / digest / "sheet.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sheet_html(list(zip(ids, groups, images, strict=True))),
                    encoding="utf-8")
    for group, count in Counter(groups).most_common():
        print(f"{count:6d}  {group}")
    print(f"posts {provider.post_count}, sheet {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
