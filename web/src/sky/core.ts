/**
 * The pure core of the results sky (the Your results screen).
 *
 * The sky holds one drawing for each revealed day: the day's own
 * sketch, drawn as a constellation. The drawings stand scattered, with
 * no grid, and each is sized by its result. When the page scrolls out
 * of the sky, each drawing folds into its star and the stars go to
 * their places on the chart of the days.
 *
 * The geometry lives here as plain functions over plain numbers, as
 * board/core.ts holds the geometry of the skill board, so the unit
 * tests check it without a browser. sky/engine.ts moves the nodes and
 * holds no arithmetic of its own beyond blending two places.
 *
 * The sky reads revealed days alone, so it says nothing of the open
 * day (I7). It draws what the history holds and grades nothing: a size
 * is a drawing of the result, and the line of chance on the chart is
 * the one reference (I2). No number here is a threshold. Each constant
 * is a layout limit.
 */

export type SkyPoint = readonly [number, number];

/**
 * How many of the latest days the sky holds at most. A layout limit
 * only: each drawing is one request for a stored sketch, and more
 * stars than this touch each other on the chart of a phone. The table
 * under the sky holds each day.
 */
export const SKY_DAYS = 60;

export function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value));
}

export function lerp(from: number, to: number, t: number): number {
  return from + (to - from) * t;
}

/** 0 before `low`, 1 after `high`, and a smooth step between. */
export function smooth(value: number, low: number, high: number): number {
  const t = clamp((value - low) / (high - low), 0, 1);
  return t * t * (3 - 2 * t);
}

/** Slow at each end, for a move from one place to another. */
export function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

/**
 * How large a drawing is for its result, as a share of the largest
 * size. The curve is steep on purpose (owner request 2026-11-21: "the
 * size differences should be more extreme"): a result of 96% draws at
 * about 0.92, one of 50% at about 0.31, and one of 9% at about 0.14.
 * A drawing at 96% is thus three times as wide as one at 50%.
 */
export function sizeShare(p: number): number {
  return 0.14 + 0.86 * clamp(p, 0, 1) ** 2.3;
}

/** A number from a text, the same on each visit (FNV-1a, 32 bits). */
export function seedOf(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/**
 * A random sequence from a seed (mulberry32). The sky uses no
 * `Math.random`: the same player gets the same sky on each visit.
 */
export function randomOf(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export interface SkyRect {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** The part of the sky that holds drawings, less the parts kept clear. */
export interface SkyBounds extends SkyRect {
  /** The title and the hint at the foot: no drawing stands on them. */
  keepOut: ReadonlyArray<SkyRect>;
}

export interface Scatter {
  /** The middle of each drawing, in the order of the results given. */
  x: Float32Array;
  y: Float32Array;
  /** The side of each drawing's square. */
  size: Float32Array;
  /** The side of the largest drawing. */
  largest: number;
}

/** The share of a drawing's side that it keeps clear as a radius. */
export const FOOTPRINT = 0.54;
/** The least space between two drawings, in pixels. */
const GAP = 3;
/** The largest side of a drawing, however empty the sky is. */
const LARGEST_SIDE = 340;
/** The smallest side tried before the scatter gives up on a size. */
const SMALLEST_SIDE = 6;
/** How many times the search for the largest size halves its range. */
const HALVINGS = 10;

function blocks(rect: SkyRect, x: number, y: number, radius: number): boolean {
  return (
    x + radius > rect.left &&
    x - radius < rect.right &&
    y + radius > rect.top &&
    y - radius < rect.bottom
  );
}

/**
 * One try at a size: each drawing, the largest first, takes of many
 * random places the one farthest from the drawings that are down, so
 * the small ones fill the gaps and nothing lines up. Null when a
 * drawing finds no free place.
 */
function place(
  ps: ReadonlyArray<number>,
  order: ReadonlyArray<number>,
  bounds: SkyBounds,
  seed: number,
  largest: number,
): { x: Float32Array; y: Float32Array } | null {
  const count = ps.length;
  const random = randomOf(seed);
  const tries = count > 120 ? 26 : 90;
  const x = new Float32Array(count);
  const y = new Float32Array(count);
  const radii = new Float32Array(count);
  const width = bounds.right - bounds.left;
  const height = bounds.bottom - bounds.top;
  for (let placed = 0; placed < count; placed += 1) {
    const index = order[placed] as number;
    const radius = largest * sizeShare(ps[index] as number) * FOOTPRINT + GAP;
    if (width < 2 * radius || height < 2 * radius) {
      return null;
    }
    let bestX = 0;
    let bestY = 0;
    let bestRoom = -1;
    for (let attempt = 0; attempt < tries; attempt += 1) {
      const cx = bounds.left + radius + random() * (width - 2 * radius);
      const cy = bounds.top + radius + random() * (height - 2 * radius);
      if (bounds.keepOut.some((rect) => blocks(rect, cx, cy, radius))) {
        continue;
      }
      let room = Number.POSITIVE_INFINITY;
      for (let other = 0; other < placed && room >= 0; other += 1) {
        const down = order[other] as number;
        const dx = cx - (x[down] as number);
        const dy = cy - (y[down] as number);
        room = Math.min(
          room,
          Math.sqrt(dx * dx + dy * dy) - radius - (radii[down] as number),
        );
      }
      if (room >= 0 && room > bestRoom) {
        bestRoom = room;
        bestX = cx;
        bestY = cy;
      }
    }
    if (bestRoom < 0) {
      return null;
    }
    x[index] = bestX;
    y[index] = bestY;
    radii[index] = radius;
  }
  return { x, y };
}

/**
 * Where each drawing stands and how large it is. `ps` holds the
 * results, each from 0 to 1. The size of a drawing follows its result
 * (`sizeShare`), and the scale of them all is the largest that still
 * fits the bounds with no two drawings on each other. Pure: the same
 * results, bounds, and seed give the same sky.
 */
export function scatter(
  ps: ReadonlyArray<number>,
  bounds: SkyBounds,
  seed: number,
): Scatter {
  const count = ps.length;
  const order = ps
    .map((_, index) => index)
    .sort((a, b) => (ps[b] as number) - (ps[a] as number));
  const width = Math.max(0, bounds.right - bounds.left);
  const height = Math.max(0, bounds.bottom - bounds.top);
  let low = SMALLEST_SIDE;
  let high = Math.max(low, Math.min(height * 0.5, width * 0.46, LARGEST_SIDE));
  let found = place(ps, order, bounds, seed, low);
  for (let step = 0; step < HALVINGS && found !== null; step += 1) {
    const middle = (low + high) / 2;
    const tried = place(ps, order, bounds, seed, middle);
    if (tried === null) {
      high = middle;
    } else {
      low = middle;
      found = tried;
    }
  }
  const size = new Float32Array(count);
  let largest = 0;
  for (let index = 0; index < count; index += 1) {
    size[index] = low * sizeShare(ps[index] as number);
    largest = Math.max(largest, size[index] as number);
  }
  if (found === null) {
    // No room at the smallest size (a window with no height): each
    // drawing stands in the middle. The chart under the sky still holds
    // each day in its place.
    const x = new Float32Array(count).fill(bounds.left + width / 2);
    const y = new Float32Array(count).fill(bounds.top + height / 2);
    return { x, y, size, largest };
  }
  return { x: found.x, y: found.y, size, largest };
}

/** The radius of a day's star in the sky, from the side of its drawing. */
export function skyStarRadius(size: number): number {
  return clamp(size * 0.03, 1.5, 7);
}

/** The radius of a day's star on the chart: a larger star is a better result. */
export function chartStarRadius(p: number, narrow: boolean): number {
  const small = narrow ? 2 : 2.6;
  const large = narrow ? 4.6 : 6;
  return small + clamp(p, 0, 1) * (large - small);
}

/**
 * Where a day's star stands on the chart: the days in order from the
 * left, the newest on the right, and the height is the result, from 0%
 * at the foot to 100% at the top. One day stands in the middle.
 */
export function chartPlace(
  index: number,
  count: number,
  p: number,
  box: SkyRect,
): { x: number; y: number } {
  const along = count <= 1 ? 0.5 : index / (count - 1);
  return {
    x: lerp(box.left, box.right, along),
    y: lerp(box.bottom, box.top, clamp(p, 0, 1)),
  };
}

function distanceToLine(point: SkyPoint, from: SkyPoint, to: SkyPoint): number {
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const length = dx * dx + dy * dy;
  if (length === 0) {
    return Math.hypot(point[0] - from[0], point[1] - from[1]);
  }
  const t = clamp(
    ((point[0] - from[0]) * dx + (point[1] - from[1]) * dy) / length,
    0,
    1,
  );
  return Math.hypot(point[0] - from[0] - t * dx, point[1] - from[1] - t * dy);
}

/**
 * A line with fewer points that stays within `tolerance` of the line
 * given (Ramer, Douglas, and Peucker). The two ends stay.
 */
export function simplify(
  points: ReadonlyArray<SkyPoint>,
  tolerance: number,
): SkyPoint[] {
  if (points.length <= 2) {
    return [...points];
  }
  const keep = new Uint8Array(points.length);
  keep[0] = 1;
  keep[points.length - 1] = 1;
  const spans: Array<[number, number]> = [[0, points.length - 1]];
  while (spans.length > 0) {
    const [first, last] = spans.pop() as [number, number];
    let farthest = -1;
    let most = tolerance;
    for (let index = first + 1; index < last; index += 1) {
      const distance = distanceToLine(
        points[index] as SkyPoint,
        points[first] as SkyPoint,
        points[last] as SkyPoint,
      );
      if (distance > most) {
        most = distance;
        farthest = index;
      }
    }
    if (farthest >= 0) {
      keep[farthest] = 1;
      spans.push([first, farthest], [farthest, last]);
    }
  }
  return points.filter((_, index) => keep[index] === 1);
}

export interface FigureLine {
  points: SkyPoint[];
  /** Absent for ink, as in a stored stroke. */
  color: string | undefined;
}

/** A sketch as a constellation, in a square from 0 to 1. */
export interface Figure {
  /** Each stroke of the sketch, as a thin line. */
  lines: FigureLine[];
  /** The stars of the figure: the ends and the corners of its strokes. */
  dots: SkyPoint[];
  /** The star that stands for the day: the first point drawn. */
  anchor: SkyPoint;
}

/** The share of the square left clear at each edge. */
const FIGURE_MARGIN = 0.06;
/** The least span a sketch is taken to have: a dot does not fill the square. */
const LEAST_SPAN = 0.12;
/** How far a drawn line may move when its points are thinned. */
const LINE_TOLERANCE = 0.004;
/** How far a line bends before the bend gets a star. */
const CORNER_TOLERANCE = 0.035;
/** The least distance between two stars of a figure. */
const STAR_GAP = 0.05;
/** The most stars one figure holds. */
const MOST_STARS = 36;

/**
 * The constellation of a sketch, or null for a send with no sketch.
 * The sketch is fitted to the square, so the size of a drawing in the
 * sky is the size of its result and not of how much of the canvas the
 * player used. Stroke points are fractions of the canvas, as stored.
 */
export function figureOf(
  strokes: ReadonlyArray<{
    points: ReadonlyArray<SkyPoint>;
    color?: string | undefined;
  }>,
): Figure | null {
  let left = Number.POSITIVE_INFINITY;
  let top = Number.POSITIVE_INFINITY;
  let right = Number.NEGATIVE_INFINITY;
  let bottom = Number.NEGATIVE_INFINITY;
  for (const stroke of strokes) {
    for (const [x, y] of stroke.points) {
      left = Math.min(left, x);
      right = Math.max(right, x);
      top = Math.min(top, y);
      bottom = Math.max(bottom, y);
    }
  }
  if (!Number.isFinite(left)) {
    return null;
  }
  const span = Math.max(right - left, bottom - top, LEAST_SPAN);
  const scale = (1 - 2 * FIGURE_MARGIN) / span;
  const middleX = (left + right) / 2;
  const middleY = (top + bottom) / 2;
  const fit = ([x, y]: SkyPoint): SkyPoint => [
    0.5 + (x - middleX) * scale,
    0.5 + (y - middleY) * scale,
  ];
  const lines: FigureLine[] = [];
  const dots: SkyPoint[] = [];
  for (const stroke of strokes) {
    if (stroke.points.length === 0) {
      continue;
    }
    const fitted = stroke.points.map(fit);
    lines.push({
      points: simplify(fitted, LINE_TOLERANCE),
      color: stroke.color,
    });
    for (const corner of simplify(fitted, CORNER_TOLERANCE)) {
      const apart = dots.every(
        (dot) => Math.hypot(dot[0] - corner[0], dot[1] - corner[1]) > STAR_GAP,
      );
      if (apart && dots.length < MOST_STARS) {
        dots.push(corner);
      }
    }
  }
  return { lines, dots, anchor: dots[0] as SkyPoint };
}
