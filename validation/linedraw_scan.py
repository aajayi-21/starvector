"""The line-drawer parameter scan (spec P2b section 4).

Re-runs the line-drawing stage on the problem images across a
parameter grid and emits a contact sheet plus ink fractions, for
eyes. The scan shares the p05 detector path (LocalLineDrawer's
detect_gray) and the p05 post-processing (core/lineart) — only the
scanned values change (P2b R1). Local and offline: no OpenRouter use,
no pool artifact writes (P2b R2). Output lands below
data/validation/.
"""

import argparse
import base64
import json
import sys
from collections.abc import Sequence
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

from core.canonical import JsonValue, quantize_measured, sha256_hex
from core.lineart import binarize_mask, prune_short_segments, render_canonical
from pipeline.config import ConfigError, load_scoring_config
from pipeline.context import load_pool_index
from pool.artifacts import load_image_bytes, write_json_pretty
from pool.preparation.config import load_preparation_config
from pool.preparation.run import wire_slot
from validation import harness

# The D1 grid: thresholds by resolutions, plus one low-pruning cell.
# The 0.50 / 512 / 10 cell is the unchanged behavior — the control.
THRESHOLDS: tuple[float, ...] = (0.30, 0.40, 0.50)
RESOLUTIONS: tuple[int, ...] = (512, 768, 1024)


class ScanCell(NamedTuple):
    """One post-processing cell of the D1 grid."""

    threshold: float
    resolution: int
    min_segment_px: int


SCAN_CELLS: tuple[ScanCell, ...] = tuple(
    ScanCell(threshold, resolution, 10)
    for resolution in RESOLUTIONS for threshold in THRESHOLDS
) + (ScanCell(0.40, 512, 5),)

# Raw detector output columns on the sheet: the unchanged resolution
# and the largest one — the D5 contingency reads the second.
RAW_COLUMNS: tuple[int, ...] = (512, 1024)

_CONTROL_COUNT = 6
_WORST_COUNT = 20
_THUMB = 120


def cell_label(cell: ScanCell) -> str:
    return f"t{cell.threshold:.2f} r{cell.resolution} s{cell.min_segment_px}"


def control_image_ids(image_ids: Sequence[str], group_ids: Sequence[str],
                      largest_group: str, count: int = _CONTROL_COUNT
                      ) -> tuple[str, ...]:
    """Seeded stable controls: pool images out of the largest group."""
    candidates = [image_id for image_id, group in zip(image_ids, group_ids)
                  if group != largest_group]
    candidates.sort(key=lambda image_id: sha256_hex("scan-control:" + image_id))
    return tuple(sorted(candidates[:count]))


def worst_pair_keys(trial_rows: Sequence[dict], count: int = _WORST_COUNT
                    ) -> tuple[str, ...]:
    """The pair keys of the worst-ranked V1 trials, worst first."""
    ordered = sorted(trial_rows,
                     key=lambda row: (-int(row["target_rank"]),
                                      str(row["pair_key"])))
    return tuple(str(row["pair_key"]) for row in ordered[:count])


def ink_fraction(drawing_png: bytes) -> float:
    """The dark-pixel fraction of one rendered drawing."""
    with Image.open(BytesIO(drawing_png)) as image:
        pixels = np.asarray(image.convert("L"))
    return float((pixels < 128).mean())


def _thumb_uri(image: Image.Image, fmt: str) -> str:
    image = image.copy()
    image.thumbnail((_THUMB, _THUMB))
    buffer = BytesIO()
    if fmt == "JPEG":
        image.convert("RGB").save(buffer, format="JPEG", quality=66)
        mime = "image/jpeg"
    else:
        image.convert("L").save(buffer, format="PNG", optimize=True)
        mime = "image/png"
    return f"data:{mime};base64,{base64.b64encode(buffer.getvalue()).decode()}"


def build_sheet_html(header_labels: Sequence[str],
                     rows: Sequence[tuple[str, str, Sequence[str]]]) -> str:
    """The contact sheet: one row for each image, one column for each cell.

    Each row holds its marker, its key, and the image data URIs in
    header sequence. Pure — testable without the detector.
    """
    head = "".join(f"<th>{label}</th>" for label in header_labels)
    body = []
    for kind, key, uris in rows:
        cells = "".join(f'<td><img src="{uri}" alt=""></td>' for uri in uris)
        body.append(
            f'<tr><th scope="row"><span class="kind {kind}">{kind}</span>'
            f"<br>{key}</th>{cells}</tr>")
    return f"""<title>Line-drawer parameter scan</title>
<style>
:root {{
  --ground: #f7f8f6; --card: #ffffff; --ink: #20302c; --muted: #5c6f6a;
  --line: #d8dfdc; --accent: #2e6e63; --flag: #92620f;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground: #161b1a; --card: #1e2523; --ink: #e6ebe9; --muted: #93a39e;
    --line: #313b38; --accent: #6fbfae; --flag: #d9a84e;
  }}
}}
:root[data-theme="dark"] {{
  --ground: #161b1a; --card: #1e2523; --ink: #e6ebe9; --muted: #93a39e;
  --line: #313b38; --accent: #6fbfae; --flag: #d9a84e;
}}
body {{ background: var(--ground); color: var(--ink); margin: 0;
  padding: 2rem; font: 14px/1.5 ui-sans-serif, system-ui, sans-serif; }}
h1 {{ font-size: 1.3rem; }}
p {{ color: var(--muted); max-width: 70ch; }}
.wrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid var(--line); padding: .3rem;
  background: var(--card); }}
thead th {{ font: .68rem/1.3 ui-monospace, monospace; color: var(--muted);
  position: sticky; top: 0; }}
tbody th {{ font: .66rem/1.4 ui-monospace, monospace; color: var(--muted);
  text-align: left; max-width: 11ch; overflow-wrap: anywhere; }}
td img {{ display: block; width: {_THUMB}px; height: auto; background: #fff; }}
.kind {{ font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }}
.kind.group {{ color: var(--flag); }}
.kind.worst {{ color: var(--accent); }}
.kind.control {{ color: var(--muted); }}
</style>
<h1>Line-drawer parameter scan — spec P2b section 4</h1>
<p>Raw columns show the detector output before post-processing (the D5
contingency reads raw r1024). Cell captions: t threshold, r detector
resolution, s minimum segment. The t0.50 r512 s10 column is the
unchanged behavior — the control.</p>
<div class="wrap"><table><thead><tr><th>image</th>{head}</tr></thead>
<tbody>{"".join(body)}</tbody></table></div>
"""


def run_scan(*, prep_config_path: Path, scoring_config_path: Path,
             data_root: Path, out_path: Path) -> dict[str, JsonValue]:
    """The full scan: select images, render the grid, write the sheet."""
    try:
        import torch  # noqa: F401
    except ImportError as error:
        raise SystemExit(
            "the scan needs the local torch stack — sync the local-xpu or "
            "local-cuda group first") from error

    scoring_config = load_scoring_config(scoring_config_path)
    prep_config = load_preparation_config(prep_config_path)
    loaded = load_pool_index(Path(scoring_config.input.preparation_record),
                             data_root, dev_only=scoring_config.report.dev_only)
    index = loaded.index

    from collections import Counter
    largest_group = Counter(index.group_ids).most_common(1)[0][0]
    group_members = tuple(image_id for image_id, group
                          in zip(index.image_ids, index.group_ids)
                          if group == largest_group)
    controls = control_image_ids(index.image_ids, index.group_ids,
                                 largest_group)

    trials_files = sorted(data_root.glob("validation/v1/*/*/trials.jsonl"))
    if not trials_files:
        raise SystemExit("no V1 trials found — run validation.v1 first")
    trial_rows = [json.loads(line)
                  for line in trials_files[-1].read_text().splitlines()]
    worst_keys = worst_pair_keys(trial_rows)
    source = harness.wire_sketch_pairs(scoring_config, data_root)
    worst_pairs = harness.pairs_by_key(source, set(worst_keys))

    subjects: list[tuple[str, str, bytes]] = []
    for image_id in group_members:
        subjects.append(("group", image_id[:10],
                         load_image_bytes(data_root, image_id)))
    for key in worst_keys:
        subjects.append(("worst", key, worst_pairs[key].photo_bytes))
    for image_id in controls:
        subjects.append(("control", image_id[:10],
                         load_image_bytes(data_root, image_id)))

    drawer = wire_slot("line_drawer", prep_config, data_root)
    canvas = prep_config.linedraw.canvas_px
    width = prep_config.linedraw.line_width_px

    header = (["photo"] + [f"raw r{r}" for r in RAW_COLUMNS]
              + [cell_label(cell) for cell in SCAN_CELLS])
    rows: list[tuple[str, str, list[str]]] = []
    ink: dict[str, JsonValue] = {}
    for position, (kind, key, photo) in enumerate(subjects):
        with Image.open(BytesIO(photo)) as image:
            uris = [_thumb_uri(image, "JPEG")]
        gray_by_resolution = {
            resolution: drawer.detect_gray(photo, resolution)
            for resolution in RESOLUTIONS}
        for resolution in RAW_COLUMNS:
            # Show the raw output dark-on-white, as the drawings are.
            raw = (255 - (gray_by_resolution[resolution] * 255)).astype("uint8")
            uris.append(_thumb_uri(Image.fromarray(raw, mode="L"), "PNG"))
        cell_ink: dict[str, JsonValue] = {}
        for cell in SCAN_CELLS:
            mask = binarize_mask(gray_by_resolution[cell.resolution],
                                 cell.threshold, lines_are_dark=False)
            mask = prune_short_segments(mask, cell.min_segment_px)
            drawing = render_canonical(mask, canvas, width)
            cell_ink[cell_label(cell)] = quantize_measured(
                ink_fraction(drawing))
            with Image.open(BytesIO(drawing)) as image:
                uris.append(_thumb_uri(image, "PNG"))
        ink[f"{kind}:{key}"] = cell_ink
        rows.append((kind, key, uris))
        print(f"[{position + 1}/{len(subjects)}] {kind} {key}",
              file=sys.stderr)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_sheet_html(header, rows), encoding="utf-8")
    summary: dict[str, JsonValue] = {
        "cells": [cell_label(cell) for cell in SCAN_CELLS],
        "group_members": len(group_members),
        "worst_pairs": len(worst_keys),
        "controls": len(controls),
        "ink_fractions": ink,
    }
    write_json_pretty(out_path.with_name("scan.json"), summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.linedraw_scan")
    parser.add_argument("--prep-config",
                        default="configs/preparation/dev-wit.json")
    parser.add_argument("--scoring-config",
                        default="configs/scoring/dev-wit.json")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--out",
                        default="data/validation/linedraw-scan.html")
    arguments = parser.parse_args(argv)
    try:
        run_scan(prep_config_path=Path(arguments.prep_config),
                 scoring_config_path=Path(arguments.scoring_config),
                 data_root=Path(arguments.data_root),
                 out_path=Path(arguments.out))
    except ConfigError as error:
        print(f"config error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
