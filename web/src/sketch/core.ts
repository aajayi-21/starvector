/**
 * The pure sketch core (spec W1 §9): the drawing document, its
 * reducers, the undo history, capture-time point filtering, segment
 * hit-testing, and serialization to the frozen wire record. No DOM,
 * no clock, no RNG — stroke identifiers come from the caller.
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

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value));

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
