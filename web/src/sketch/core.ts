/**
 * The pure sketch core (spec W1 §9): the drawing document, its
 * reducers, the eraser's cut geometry, the undo history, capture-time
 * point filtering, segment hit-testing, and serialization to the
 * frozen wire record. No DOM, no clock, no RNG — stroke identifiers
 * come from the caller.
 */

import type { WireRecord, WireStroke } from "../api/types";
import { wireOf } from "./palette";

// ── Spec-fixed constants (§9) ───────────────────────────────────

export const ROUND_DECIMALS = 4;
export const MIN_POINT_GAP_PX = 0.5;
export const STROKE_WIDTH_PX = 3;
export const SELECT_TOLERANCE_TOUCH_PX = 12;

export function selectTolerance(strokeWidthPx: number): number {
  return Math.max(strokeWidthPx / 2 + 4, 8);
}

/** The eraser's radius in CSS pixels: the select tolerances, used again. */
export const ERASER_RADIUS_PX = 8;
export const ERASER_RADIUS_TOUCH_PX = 12;

/**
 * The eraser's three sizes, as multiples of its radius: small, middle,
 * and large. The middle one is the size the eraser had before it had
 * sizes. A display choice of the drawing tool: the stored strokes are
 * the same whichever size cut them.
 */
export const ERASER_SCALES = [0.6, 1, 2] as const;
/** The size the eraser starts with: the middle one. */
export const ERASER_SCALE_START = 1;

export function eraserRadius(pointerType: string, scale = 1): number {
  const base =
    pointerType === "touch" ? ERASER_RADIUS_TOUCH_PX : ERASER_RADIUS_PX;
  return base * scale;
}

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

// ── The document ────────────────────────────────────────────────

export type Point = readonly [number, number];

export interface CoreStroke {
  readonly id: number;
  /** Normalized [0, 1] coordinates. */
  readonly points: ReadonlyArray<Point>;
  /** Index into the palette; 0 is ink. */
  readonly colorIndex: number;
}

export interface SketchGroup {
  readonly id: string;
  readonly label: string;
}

export interface SketchRelation {
  readonly relation: string;
  readonly of: readonly [string, string];
}

export interface SketchDoc {
  readonly strokes: ReadonlyArray<CoreStroke>;
  /** Creation order. No reducer removes a group — ids never dangle. */
  readonly groups: ReadonlyArray<SketchGroup>;
  /** strokeId -> groupId. */
  readonly assignments: Readonly<Record<number, string>>;
  readonly relations: ReadonlyArray<SketchRelation>;
}

export const EMPTY_DOC: SketchDoc = {
  strokes: [],
  groups: [],
  assignments: {},
  relations: [],
};

// ── Reducers — each returns a new document ──────────────────────

export function addStroke(
  doc: SketchDoc,
  points: ReadonlyArray<Point>,
  colorIndex: number,
  id: number,
): SketchDoc {
  return {
    ...doc,
    strokes: [...doc.strokes, { id, points, colorIndex }],
  };
}

/** Clear is a recorded operation: strokes, groups, and relations go. */
export function clearSketch(doc: SketchDoc): SketchDoc {
  void doc;
  return EMPTY_DOC;
}

/** Group ids follow the page rule: "g" + (count + 1), never reused. */
export function makeGroup(
  doc: SketchDoc,
  strokeIds: ReadonlyArray<number>,
  label: string,
): SketchDoc {
  const id = `g${doc.groups.length + 1}`;
  const assignments = { ...doc.assignments };
  for (const strokeId of strokeIds) {
    assignments[strokeId] = id;
  }
  return {
    ...doc,
    groups: [...doc.groups, { id, label }],
    assignments,
  };
}

export function ungroupStroke(doc: SketchDoc, strokeId: number): SketchDoc {
  if (!(strokeId in doc.assignments)) {
    return doc;
  }
  const assignments = { ...doc.assignments };
  delete assignments[strokeId];
  return { ...doc, assignments };
}

export function addRelation(
  doc: SketchDoc,
  relation: string,
  of: readonly [string, string],
): SketchDoc {
  // Undo can rewind a makeGroup while stale UI state still names its
  // id — a relation naming an unknown group would serialize into a
  // record intake refuses, so the reducer drops it here.
  const known = new Set(doc.groups.map((group) => group.id));
  if (!known.has(of[0]) || !known.has(of[1])) {
    return doc;
  }
  return { ...doc, relations: [...doc.relations, { relation, of }] };
}

export function removeRelation(doc: SketchDoc, index: number): SketchDoc {
  return {
    ...doc,
    relations: doc.relations.filter((_, at) => at !== index),
  };
}

// ── Erasing — cut strokes where the eraser passes ───────────────

/**
 * Numeric floor of the cut geometry, in CSS pixels and in segment
 * parameters: an erased run this short is a tangent touch and erases
 * nothing, and a cut this near a vertex is the vertex.
 */
const ERASE_EPS = 1e-9;

/** A run [from, to] of a segment's parameter, 0 at its start, 1 at its end. */
type Span = readonly [number, number];

/** The part of the line A + t·d that satisfies low <= start + t·step <= high. */
function slab(start: number, step: number, low: number, high: number): Span {
  if (step === 0) {
    return start >= low && start <= high
      ? [Number.NEGATIVE_INFINITY, Number.POSITIVE_INFINITY]
      : [1, 0];
  }
  const first = (low - start) / step;
  const second = (high - start) / step;
  return first <= second ? [first, second] : [second, first];
}

/** The part of the segment A→B inside the closed disc at C, or null. */
function discSpan(a: Point, b: Point, c: Point, radius: number): Span | null {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const fx = a[0] - c[0];
  const fy = a[1] - c[1];
  const lengthSq = dx * dx + dy * dy;
  const offset = fx * fx + fy * fy - radius * radius;
  if (lengthSq === 0) {
    return offset <= 0 ? [0, 1] : null;
  }
  const half = dx * fx + dy * fy;
  const root = half * half - lengthSq * offset;
  if (root < 0) {
    return null;
  }
  const spread = Math.sqrt(root);
  const from = Math.max(0, (-half - spread) / lengthSq);
  const to = Math.min(1, (-half + spread) / lengthSq);
  return from <= to ? [from, to] : null;
}

/**
 * The part of the segment A→B inside the rectangle that the eraser
 * sweeps between P and Q: within `radius` of the line PQ, and between
 * its two ends. Null when P and Q are one point: the discs cover it.
 */
function sweepSpan(
  a: Point,
  b: Point,
  p: Point,
  q: Point,
  radius: number,
): Span | null {
  const ux = q[0] - p[0];
  const uy = q[1] - p[1];
  const length = Math.hypot(ux, uy);
  if (length === 0) {
    return null;
  }
  const alongX = ux / length;
  const alongY = uy / length;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const fx = a[0] - p[0];
  const fy = a[1] - p[1];
  const along = slab(
    fx * alongX + fy * alongY,
    dx * alongX + dy * alongY,
    0,
    length,
  );
  const across = slab(
    fy * alongX - fx * alongY,
    dy * alongX - dx * alongY,
    -radius,
    radius,
  );
  const from = Math.max(0, along[0], across[0]);
  const to = Math.min(1, along[1], across[1]);
  return from <= to ? [from, to] : null;
}

/**
 * The part of the segment A→B inside the capsule of the eraser moving
 * from P to Q: the disc at each end and the rectangle between them. A
 * capsule is convex, so the part is one run.
 */
function capsuleSpan(
  a: Point,
  b: Point,
  p: Point,
  q: Point,
  radius: number,
): Span | null {
  const parts = [
    discSpan(a, b, p, radius),
    discSpan(a, b, q, radius),
    sweepSpan(a, b, p, q, radius),
  ].filter((part): part is Span => part !== null);
  if (parts.length === 0) {
    return null;
  }
  return [
    Math.min(...parts.map((part) => part[0])),
    Math.max(...parts.map((part) => part[1])),
  ];
}

/** Sorted runs, joined where they touch or overlap. */
function mergeSpans(spans: ReadonlyArray<Span>): Span[] {
  const sorted = [...spans].sort((x, y) => x[0] - y[0]);
  const merged: Span[] = [];
  for (const span of sorted) {
    const last = merged[merged.length - 1];
    if (last !== undefined && span[0] <= last[1] + ERASE_EPS) {
      merged[merged.length - 1] = [last[0], Math.max(last[1], span[1])];
    } else {
      merged.push(span);
    }
  }
  return merged;
}

function pathLength(points: ReadonlyArray<Point>): number {
  let total = 0;
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1] as Point;
    const to = points[index] as Point;
    total += Math.hypot(to[0] - from[0], to[1] - from[1]);
  }
  return total;
}

/**
 * The pieces of one stroke that the eraser leaves, as normalized
 * points, or null when the eraser does not touch the stroke. An
 * untouched vertex keeps its own point object, so it does not drift;
 * a cut makes a new point at the eraser's edge.
 */
function erasedPieces(
  stroke: CoreStroke,
  eraser: ReadonlyArray<Point>,
  radiusPx: number,
  cssWidth: number,
  cssHeight: number,
): Point[][] | null {
  const css = stroke.points.map(
    ([x, y]): Point => [x * cssWidth, y * cssHeight],
  );
  const capsules: Array<readonly [Point, Point]> =
    eraser.length === 1
      ? [[eraser[0] as Point, eraser[0] as Point]]
      : eraser.slice(1).map((to, index) => [eraser[index] as Point, to]);

  if (css.length === 1) {
    const only = css[0] as Point;
    const hit = capsules.some(
      ([p, q]) => capsuleSpan(only, only, p, q, radiusPx) !== null,
    );
    return hit ? [] : null;
  }

  // The erased runs of each segment of the stroke.
  let touched = false;
  const erased: Span[][] = [];
  for (let index = 0; index < css.length - 1; index += 1) {
    const a = css[index] as Point;
    const b = css[index + 1] as Point;
    const length = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const spans = capsules
      .map(([p, q]) => capsuleSpan(a, b, p, q, radiusPx))
      .filter((span): span is Span => span !== null)
      // A run with no length is a tangent touch: it erases nothing.
      .filter(
        (span) => (span[1] - span[0]) * length > ERASE_EPS || length === 0,
      );
    const merged = mergeSpans(spans);
    touched = touched || merged.length > 0;
    erased.push(merged);
  }
  if (!touched) {
    return null;
  }

  const cutPoint = (index: number, t: number): Point => {
    const a = css[index] as Point;
    const b = css[index + 1] as Point;
    return [
      clamp01((a[0] + t * (b[0] - a[0])) / cssWidth),
      clamp01((a[1] + t * (b[1] - a[1])) / cssHeight),
    ];
  };
  const cssOf = (point: Point): Point => [
    point[0] * cssWidth,
    point[1] * cssHeight,
  ];

  const pieces: Point[][] = [];
  let open: Point[] | null = null;
  const close = () => {
    // A piece is a line: two points or more, and long enough to be
    // more than the capture filter's gap, so it is a real mark after
    // the wire record rounds it.
    if (
      open !== null &&
      open.length >= 2 &&
      pathLength(open.map(cssOf)) >= MIN_POINT_GAP_PX
    ) {
      pieces.push(open);
    }
    open = null;
  };

  for (let index = 0; index < css.length - 1; index += 1) {
    const spans = erased[index] as Span[];
    const first = spans[0];
    if (open === null && (first === undefined || first[0] > ERASE_EPS)) {
      open = [stroke.points[index] as Point];
    }
    for (const [from, to] of spans) {
      if (open !== null) {
        if (from > ERASE_EPS) {
          (open as Point[]).push(cutPoint(index, from));
        }
        close();
      }
      if (to < 1 - ERASE_EPS) {
        open = [cutPoint(index, to)];
      }
    }
    if (open !== null) {
      (open as Point[]).push(stroke.points[index + 1] as Point);
    }
  }
  close();
  return pieces;
}

export interface EraseResult {
  readonly doc: SketchDoc;
  /** The first stroke identifier that the erase did not use. */
  readonly nextId: number;
}

/**
 * Erase what is under the eraser, and nothing else. The eraser is a
 * disc of `radiusPx` that moves along `eraserPathCss` (CSS pixels, one
 * point for a tap): each stroke loses the parts inside it, cut at the
 * eraser's edge and not at the stroke's own points.
 *
 * A stroke that the eraser touches gives way to its remaining pieces,
 * in its own position in the drawing sequence. Each piece is a stroke
 * with a new identifier from `firstNewId` up, the color of the stroke
 * it came from, and that stroke's group. A stroke that the eraser does
 * not touch keeps its object and its identifier. Groups and relations
 * stay: a group can lose each of its strokes, as it can by ungrouping.
 *
 * When the eraser touches nothing, the result is the same `doc` object,
 * so the caller records no step. The wire record does not change: a
 * piece is an ordinary stroke.
 */
export function eraseAlong(
  doc: SketchDoc,
  eraserPathCss: ReadonlyArray<Point>,
  radiusPx: number,
  cssWidth: number,
  cssHeight: number,
  firstNewId: number,
): EraseResult {
  const first = eraserPathCss[0];
  if (first === undefined || doc.strokes.length === 0) {
    return { doc, nextId: firstNewId };
  }
  // The box of the eraser's path: a stroke with no point near it is
  // not looked at further.
  let left = first[0];
  let right = first[0];
  let top = first[1];
  let bottom = first[1];
  for (const [x, y] of eraserPathCss) {
    left = Math.min(left, x);
    right = Math.max(right, x);
    top = Math.min(top, y);
    bottom = Math.max(bottom, y);
  }
  left -= radiusPx;
  right += radiusPx;
  top -= radiusPx;
  bottom += radiusPx;
  const near = (stroke: CoreStroke): boolean => {
    let minX = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    for (const [x, y] of stroke.points) {
      minX = Math.min(minX, x * cssWidth);
      maxX = Math.max(maxX, x * cssWidth);
      minY = Math.min(minY, y * cssHeight);
      maxY = Math.max(maxY, y * cssHeight);
    }
    return minX <= right && maxX >= left && minY <= bottom && maxY >= top;
  };

  let nextId = firstNewId;
  let changed = false;
  const strokes: CoreStroke[] = [];
  const assignments: Record<number, string> = { ...doc.assignments };
  for (const stroke of doc.strokes) {
    const pieces = near(stroke)
      ? erasedPieces(stroke, eraserPathCss, radiusPx, cssWidth, cssHeight)
      : null;
    if (pieces === null) {
      strokes.push(stroke);
      continue;
    }
    changed = true;
    const groupId = assignments[stroke.id];
    delete assignments[stroke.id];
    for (const points of pieces) {
      strokes.push({ id: nextId, points, colorIndex: stroke.colorIndex });
      if (groupId !== undefined) {
        assignments[nextId] = groupId;
      }
      nextId += 1;
    }
  }
  if (!changed) {
    return { doc, nextId: firstNewId };
  }
  return { doc: { ...doc, strokes, assignments }, nextId };
}

// ── History — whole-document snapshots ──────────────────────────

export interface DocHistory {
  readonly states: ReadonlyArray<SketchDoc>;
  readonly index: number;
}

export function historyOf(doc: SketchDoc): DocHistory {
  return { states: [doc], index: 0 };
}

export function current(history: DocHistory): SketchDoc {
  return history.states[history.index] ?? EMPTY_DOC;
}

/** A new operation after undo truncates the redo tail. */
export function pushDoc(history: DocHistory, doc: SketchDoc): DocHistory {
  const states = [...history.states.slice(0, history.index + 1), doc];
  return { states, index: states.length - 1 };
}

export const canUndo = (history: DocHistory): boolean => history.index > 0;
export const canRedo = (history: DocHistory): boolean =>
  history.index < history.states.length - 1;

export function undo(history: DocHistory): DocHistory {
  return canUndo(history) ? { ...history, index: history.index - 1 } : history;
}

export function redo(history: DocHistory): DocHistory {
  return canRedo(history) ? { ...history, index: history.index + 1 } : history;
}

// ── Capture-time point filtering ────────────────────────────────

/**
 * CSS-pixel capture points -> normalized stroke points. Points
 * closer than MIN_POINT_GAP_PX (in CSS space) to the last kept
 * point are dropped; the final point is always kept so the stroke
 * ends where the pointer ended.
 */
export function filterPoints(
  rawCssPoints: ReadonlyArray<Point>,
  cssWidth: number,
  cssHeight: number,
): Point[] {
  const kept: Point[] = [];
  let lastKept: Point | null = null;
  for (let index = 0; index < rawCssPoints.length; index += 1) {
    const point = rawCssPoints[index];
    if (point === undefined) {
      continue;
    }
    const isFinal = index === rawCssPoints.length - 1;
    if (lastKept !== null && !isFinal) {
      const gap = Math.hypot(point[0] - lastKept[0], point[1] - lastKept[1]);
      if (gap < MIN_POINT_GAP_PX) {
        continue;
      }
    }
    kept.push(point);
    lastKept = point;
  }
  return kept.map(([x, y]) => [clamp01(x / cssWidth), clamp01(y / cssHeight)]);
}

// ── Hit-testing (selection) ─────────────────────────────────────

function segmentDistance(point: Point, a: Point, b: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const lengthSq = dx * dx + dy * dy;
  if (lengthSq === 0) {
    return Math.hypot(point[0] - a[0], point[1] - a[1]);
  }
  const t = Math.min(
    1,
    Math.max(0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / lengthSq),
  );
  return Math.hypot(point[0] - (a[0] + t * dx), point[1] - (a[1] + t * dy));
}

/**
 * The nearest stroke within tolerancePx of a CSS-pixel point —
 * minimum point-to-segment distance in CSS space (tolerance is
 * perceptual, §9). The newest stroke wins a tie.
 */
export function hitTest(
  doc: SketchDoc,
  cssPoint: Point,
  cssWidth: number,
  cssHeight: number,
  tolerancePx: number,
): number | null {
  let bestId: number | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const stroke of doc.strokes) {
    const css = stroke.points.map(
      ([x, y]): Point => [x * cssWidth, y * cssHeight],
    );
    for (let index = 0; index < css.length; index += 1) {
      const a = css[index];
      if (a === undefined) {
        continue;
      }
      const b = css[index + 1] ?? a;
      const distance = segmentDistance(cssPoint, a, b);
      // <= keeps the newest stroke on an exact tie.
      if (distance <= tolerancePx && distance <= bestDistance) {
        bestDistance = distance;
        bestId = stroke.id;
      }
    }
  }
  return bestId;
}

// ── Serialization to the frozen wire record ─────────────────────

function round(value: number): number {
  const scale = 10 ** ROUND_DECIMALS;
  return Math.round(value * scale) / scale;
}

/**
 * The wire mirror (spec W1 §6 + trial.js's assembleRecord): all
 * five keys always; each stroke row holds points (rounded to
 * ROUND_DECIMALS), group_id always (null when ungrouped), and a
 * color key only when the stroke has a palette color — ink never
 * emits the key (C1's promotion rule). pasted_text is null when the
 * textarea trims empty, else the raw untrimmed string.
 */
export function serialize(
  doc: SketchDoc,
  impressions: ReadonlyArray<string>,
  pastedTextRaw: string,
): WireRecord {
  const strokes: WireStroke[] = doc.strokes.map((stroke) => {
    const row: WireStroke = {
      points: stroke.points.map(([x, y]): [number, number] => [
        round(x),
        round(y),
      ]),
      group_id: doc.assignments[stroke.id] ?? null,
    };
    const wire = wireOf(stroke.colorIndex);
    if (wire !== null) {
      row.color = wire;
    }
    return row;
  });
  return {
    impressions: [...impressions],
    canvas_strokes: strokes,
    groups: doc.groups.map((group) => ({ id: group.id, label: group.label })),
    relations: doc.relations.map((relation) => ({
      relation: relation.relation,
      of: [relation.of[0], relation.of[1]],
    })),
    pasted_text: pastedTextRaw.trim() === "" ? null : pastedTextRaw,
  };
}
