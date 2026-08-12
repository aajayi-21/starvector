"""Layer 0 intake: validation gates and the canonical stroke render.

Implements docs/ARCHITECTURE.md section 8 through
docs/specs/scoring-path.md section 10. Frozen tier (R6). The wire
record shape checked here is permanent, with one recorded change:
a stroke can have an optional color key (owner ruling 2026-08-12,
docs/specs/color-sketches.md). Validation is at the boundary: code
after this module assumes checked input (CLAUDE.md section 3). The
render shares the pixel semantics of the pool line drawings through
core/lineart.py (R2) — the same dilation, background, and 0/255
pixel values.
"""

import math
import re

import numpy as np
from numpy.typing import NDArray

from core import lineart
from core.atoms import assemble_atoms, split_pasted_text
from core.canonical import JsonValue
from core.types import (INTAKE_CAUSES, IntakeGates, RenderParams, StrokePath,
                        Submission)

_RECORD_KEYS = ("impressions", "canvas_strokes", "groups", "relations",
                "pasted_text")
_STROKE_KEYS = ("points", "group_id")
# The one recorded change to the frozen shape: an optional stroke
# color (owner ruling 2026-08-12). The value format is fixed here.
# The palette belongs to the interface and does not touch this tier.
_STROKE_OPTIONAL_KEYS = ("color",)
_GROUP_KEYS = ("id", "label")
_RELATION_KEYS = ("relation", "of")

# Lowercase alone — one canonical spelling, thus one render byte
# stream and one cache key for equal drawings.
_COLOR_RULE = re.compile(r"#[0-9a-f]{6}")

# One point is [x, y] plus the optional entries (time, pressure).
# The optional entries stay in the raw record and are not read by
# scoring (agreed 2026-08-08).
_POINT_MIN_ENTRIES = 2
_POINT_MAX_ENTRIES = 4


class IntakeError(ValueError):
    """One submission did not clear a Layer 0 gate.

    cause is one of core.types.INTAKE_CAUSES. The message is the
    cause, a colon, and the explanation.
    """

    def __init__(self, cause: str, detail: str) -> None:
        if cause not in INTAKE_CAUSES:
            raise ValueError(f"unknown intake cause: {cause!r}")
        super().__init__(f"{cause}: {detail}")
        self.cause = cause


def _bad_shape(detail: str) -> IntakeError:
    return IntakeError("bad-shape", detail)


def _checked_string(value: object, where: str) -> str:
    if not isinstance(value, str):
        raise _bad_shape(f"{where} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate clears json.loads but no UTF-8 encoder — an
        # accepted record must stay storable and hashable forever (I4).
        raise _bad_shape(f"{where} is not encodable UTF-8 text") from None
    return value


def _checked_coordinate(value: object, where: str) -> float:
    """One point component: a finite number in the closed interval [0, 1]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad_shape(f"{where} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise _bad_shape(f"{where} must be finite")
    if number < 0.0 or number > 1.0:
        raise _bad_shape(f"{where} must be in [0, 1], got {number}")
    return number


def _checked_object(value: object, keys: tuple[str, ...], where: str,
                    optional: tuple[str, ...] = ()) -> dict:
    """One wire object: the required keys, plus optional ones alone.

    With no optional keys the check is strict set equality — the
    frozen-shape rule. An optional key can be there or not, and no
    other key is permitted.
    """
    if not isinstance(value, dict):
        raise _bad_shape(f"{where} must be an object")
    present = set(value)
    if not (set(keys) <= present <= set(keys) | set(optional)):
        detail = f"{where} must have the keys {sorted(keys)}"
        if optional:
            detail += f" plus none or some of {sorted(optional)}"
        raise _bad_shape(f"{detail}, got {sorted(present)}")
    return value


def _checked_stroke_color(value: object, where: str) -> str:
    """One stroke color: a lowercase #rrggbb string."""
    if not isinstance(value, str) or not _COLOR_RULE.fullmatch(value):
        raise _bad_shape(
            f"{where} must be a lowercase '#rrggbb' color string")
    return value


def _checked_stroke_path(raw_points: object, where: str) -> StrokePath:
    if not isinstance(raw_points, list) or not raw_points:
        raise _bad_shape(f"{where}.points must be a non-empty array")
    points = []
    for position, entry in enumerate(raw_points):
        point_where = f"{where}.points[{position}]"
        if (not isinstance(entry, list)
                or not _POINT_MIN_ENTRIES <= len(entry) <= _POINT_MAX_ENTRIES):
            raise _bad_shape(
                f"{point_where} must be an array of {_POINT_MIN_ENTRIES} to "
                f"{_POINT_MAX_ENTRIES} numbers")
        for extra in entry[_POINT_MIN_ENTRIES:]:
            if (isinstance(extra, bool)
                    or not isinstance(extra, (int, float))
                    or not math.isfinite(float(extra))):
                raise _bad_shape(
                    f"{point_where} optional entries must be finite numbers")
        points.append((_checked_coordinate(entry[0], f"{point_where}.x"),
                       _checked_coordinate(entry[1], f"{point_where}.y")))
    return tuple(points)


def _checked_record(record: JsonValue) -> dict:
    """Walk the wire record structurally, in a fixed sequence.

    Returns the record unchanged after the walk. The walk covers each
    bad-shape rule of spec P2 section 10. Reference checks (stroke
    group_id values, relation group references) come after the
    sections they point at.
    """
    top = _checked_object(record, _RECORD_KEYS, "record")

    impressions = top["impressions"]
    if not isinstance(impressions, list):
        raise _bad_shape("record.impressions must be an array")
    for position, row in enumerate(impressions):
        text = _checked_string(row, f"record.impressions[{position}]")
        if not text:
            raise _bad_shape(f"record.impressions[{position}] must not be empty")

    strokes = top["canvas_strokes"]
    if not isinstance(strokes, list):
        raise _bad_shape("record.canvas_strokes must be an array")
    for position, row in enumerate(strokes):
        where = f"record.canvas_strokes[{position}]"
        stroke = _checked_object(row, _STROKE_KEYS, where,
                                 optional=_STROKE_OPTIONAL_KEYS)
        _checked_stroke_path(stroke["points"], where)
        if stroke["group_id"] is not None:
            _checked_string(stroke["group_id"], f"{where}.group_id")
        if "color" in stroke:
            _checked_stroke_color(stroke["color"], f"{where}.color")

    groups = top["groups"]
    if not isinstance(groups, list):
        raise _bad_shape("record.groups must be an array")
    group_ids: set[str] = set()
    for position, row in enumerate(groups):
        where = f"record.groups[{position}]"
        group = _checked_object(row, _GROUP_KEYS, where)
        group_id = _checked_string(group["id"], f"{where}.id")
        if not group_id:
            raise _bad_shape(f"{where}.id must not be empty")
        if group_id in group_ids:
            raise _bad_shape(f"{where}.id is a duplicate: {group_id!r}")
        group_ids.add(group_id)
        _checked_string(group["label"], f"{where}.label")

    # Reference check: a stroke's group_id can be null (an ungrouped
    # stroke goes to the drawing atom only, agreed 2026-08-08), and a
    # non-null value must name a declared group.
    for position, row in enumerate(strokes):
        group_id = row["group_id"]
        if group_id is not None and group_id not in group_ids:
            raise _bad_shape(
                f"record.canvas_strokes[{position}].group_id names an "
                f"unknown group: {group_id!r}")

    relations = top["relations"]
    if not isinstance(relations, list):
        raise _bad_shape("record.relations must be an array")
    for position, row in enumerate(relations):
        where = f"record.relations[{position}]"
        relation = _checked_object(row, _RELATION_KEYS, where)
        name = _checked_string(relation["relation"], f"{where}.relation")
        if not name:
            raise _bad_shape(f"{where}.relation must not be empty")
        of = relation["of"]
        if not isinstance(of, list) or len(of) != 2:
            raise _bad_shape(f"{where}.of must be an array of two group "
                             "identifiers")
        for reference in of:
            _checked_string(reference, f"{where}.of")
            if reference not in group_ids:
                raise _bad_shape(f"{where}.of names an unknown group: "
                                 f"{reference!r}")

    pasted = top["pasted_text"]
    if pasted is not None:
        _checked_string(pasted, "record.pasted_text")

    return top


def _quantized(value: float, canvas_px: int) -> int:
    """Map one unit-square point component to a grid position (D2).

    Floor scaling, with the value 1.0 clamped to the last pixel.
    Integer output in [0, canvas_px - 1].
    """
    return min(int(value * canvas_px), canvas_px - 1)


def _draw_segment(mask: NDArray[np.bool_], row_a: int, col_a: int,
                  row_b: int, col_b: int) -> None:
    """Set the Bresenham line pixels between two grid points.

    The two endpoints are set. Classic integer Bresenham — no floats,
    thus the render is deterministic byte-for-byte.
    """
    delta_row = abs(row_b - row_a)
    delta_col = abs(col_b - col_a)
    step_row = 1 if row_a < row_b else -1
    step_col = 1 if col_a < col_b else -1
    error = delta_col - delta_row
    row, col = row_a, col_a
    while True:
        mask[row, col] = True
        if row == row_b and col == col_b:
            return
        doubled = 2 * error
        if doubled > -delta_row:
            error -= delta_row
            col += step_col
        if doubled < delta_col:
            error += delta_col
            row += step_row


def strokes_line_mask(strokes: tuple[StrokePath, ...] | list[StrokePath],
                      canvas_px: int) -> NDArray[np.bool_]:
    """Rasterize strokes to a boolean line image on the canvas grid.

    Each stroke becomes the Bresenham segments between its points in
    sequence. A single-point stroke sets one pixel. The output is the
    pre-dilation line image — the min-ink gate counts its pixels (D3).
    Shape (canvas_px, canvas_px).
    """
    if canvas_px < 1:
        raise ValueError(f"canvas_px must be positive, got {canvas_px}")
    mask = np.zeros((canvas_px, canvas_px), dtype=np.bool_)
    for stroke in strokes:
        quantized = [(_quantized(y, canvas_px), _quantized(x, canvas_px))
                     for x, y in stroke]
        if len(quantized) == 1:
            row, col = quantized[0]
            mask[row, col] = True
            continue
        for (row_a, col_a), (row_b, col_b) in zip(quantized, quantized[1:]):
            _draw_segment(mask, row_a, col_a, row_b, col_b)
    return mask


def render_strokes(strokes: tuple[StrokePath, ...] | list[StrokePath],
                   canvas_px: int, line_width_px: int) -> bytes:
    """Render one strokes payload as canonical PNG bytes (R1, R2).

    Rasterizes on the canvas grid, then applies the shared canonical
    render of core/lineart.py: the same dilation rule, white
    background, black lines, no anti-aliasing, 0 and 255 as the only
    pixel values. Equal strokes give byte-for-byte equal output — with
    the P1b scope, one machine and environment: the PNG encode stage
    depends on the Pillow and zlib builds.
    """
    mask = strokes_line_mask(strokes, canvas_px)
    return lineart.render_canonical(mask, canvas_px, line_width_px)


def _color_rgb(color: str) -> tuple[int, int, int]:
    """One checked '#rrggbb' string to its RGB triple."""
    return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def render_strokes_rgb(strokes: tuple[StrokePath, ...] | list[StrokePath],
                       colors: tuple[str | None, ...],
                       canvas_px: int, line_width_px: int) -> bytes:
    """Render one color strokes payload as canonical RGB PNG bytes.

    colors aligns with strokes entry for entry. A None entry paints
    as ink (black). With no color entry at all the output falls back
    to render_strokes - the byte rule of spec C1 section 2 holds
    without regard to how the caller got here.
    """
    if all(color is None for color in colors):
        return render_strokes(strokes, canvas_px, line_width_px)
    layers = [(strokes_line_mask([stroke], canvas_px),
               _color_rgb(color) if color is not None else (0, 0, 0))
              for stroke, color in zip(strokes, colors, strict=True)]
    return lineart.render_canonical_rgb(layers, canvas_px, line_width_px)


def render_submission_strokes(strokes: tuple[StrokePath, ...],
                              colors: tuple[str | None, ...] | None,
                              render: RenderParams) -> bytes:
    """The spec C1 promotion rule: one render for one drawing.

    "mono" strips colors and gives the render_strokes bytes. "rgb"
    gives the same bytes when colors is None - the byte-stable half
    of the rule that keeps colorless records and the background
    caches warm - and the RGB render when a stroke has a color.
    """
    if render.stroke_color == "mono" or colors is None:
        return render_strokes(strokes, render.canvas_px,
                              render.line_width_px)
    if render.stroke_color != "rgb":
        raise ValueError(
            f"unknown stroke_color rule: {render.stroke_color!r}")
    return render_strokes_rgb(strokes, colors, render.canvas_px,
                              render.line_width_px)


def validate_submission(record: JsonValue, gates: IntakeGates,
                        canvas_px: int) -> Submission:
    """Apply the Layer 0 gates and assemble the atom set.

    Raises IntakeError with a cause on the first violation: the
    structural walk raises bad-shape, then the gates run in a fixed
    sequence — atom-count, text-length, min-strokes, min-ink (D3).
    canvas_px comes from the preparation config through the scoring
    context (R2): the ink gate counts pre-dilation line pixels on the
    canvas grid. On a clear record, returns the Layer 1 atom set.
    """
    top = _checked_record(record)

    impressions: list = top["impressions"]
    strokes: list = top["canvas_strokes"]
    groups: list = top["groups"]
    relations: list = top["relations"]
    pasted: str | None = top["pasted_text"]
    fragments = split_pasted_text(pasted) if pasted is not None else ()

    atom_count = (len(impressions) + len(fragments) + len(groups)
                  + (1 if strokes else 0) + len(relations))
    if atom_count > gates.max_atoms:
        raise IntakeError("atom-count",
                          f"{atom_count} atoms, limit {gates.max_atoms}")

    # The gate covers each client text field: impressions, pasted
    # fragments, group labels and identifiers, and relation names.
    texts = (*impressions, *fragments,
             *(g["label"] for g in groups), *(g["id"] for g in groups),
             *(r["relation"] for r in relations))
    for text in texts:
        if len(text) > gates.max_text_length:
            raise IntakeError(
                "text-length",
                f"{len(text)} characters, limit {gates.max_text_length}")

    if strokes and len(strokes) < gates.min_strokes_whole_drawing:
        raise IntakeError(
            "min-strokes",
            f"{len(strokes)} strokes, minimum "
            f"{gates.min_strokes_whole_drawing}")

    if strokes:
        paths = [tuple((float(p[0]), float(p[1])) for p in s["points"])
                 for s in strokes]
        ink = int(strokes_line_mask(paths, canvas_px).sum())
        if ink < gates.min_ink_pixels:
            raise IntakeError(
                "min-ink",
                f"{ink} line pixels, minimum {gates.min_ink_pixels}")

    return assemble_atoms(record)
