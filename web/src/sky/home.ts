/**
 * The geometry of the home screen (screens/home.tsx): the crown of the
 * streak, the quiet stars behind the screen, and the places of the
 * faint sketches. Pure functions: no DOM, no clock, and no random
 * source but the one passed in.
 */

import { clamp, lerp, sizeShare } from "./core";

/**
 * How many days of a streak the crown draws on a wide screen and on a
 * narrow one. A layout limit only: a longer streak shows its latest
 * days, and the number beside the crown is the whole streak.
 */
export const CROWN_DAYS = 13;
export const CROWN_DAYS_NARROW = 9;

/** One day of the streak: its label, and its result when it has one. */
export interface CrownDay {
  day: string;
  /** Null for a day that was sent and has no result (not scored). */
  p: number | null;
}

/** "2026-11-18" moved by a count of days. */
export function shiftDay(day: string, by: number): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + by);
  return date.toISOString().slice(0, 10);
}

/**
 * The days of the streak that the crown draws, the oldest first. The
 * streak is the server's number: an unbroken run of calendar days that
 * ends at the newest revealed day. The crown asks nothing else of the
 * server, so the days are that run counted back from `newest`.
 */
export function crownDays(
  streak: number,
  newest: string | undefined,
  results: ReadonlyMap<string, number>,
  most: number,
): CrownDay[] {
  if (newest === undefined) {
    return [];
  }
  const count = Math.min(Math.max(0, Math.floor(streak)), most);
  return Array.from({ length: count }, (_, index) => {
    const day = shiftDay(newest, index - count + 1);
    return { day, p: results.get(day) ?? null };
  });
}

/** The share of the crown's width left clear at each end. */
const CROWN_EDGE = 0.03;

/** A place on the crown: fractions of its width and of its depth. */
export interface CrownPlace {
  /** 0 at the left edge of the crown, 1 at the right edge. */
  x: number;
  /** 0 at the top of the arc, 1 at its two ends. */
  y: number;
}

/** The arc of the crown at `u`, from 0 at its left end to 1 at its right. */
export function crownPlace(u: number): CrownPlace {
  return {
    x: CROWN_EDGE + clamp(u, 0, 1) * (1 - 2 * CROWN_EDGE),
    y: (2 * clamp(u, 0, 1) - 1) ** 2,
  };
}

/**
 * The places of `count` things on the crown, spread evenly from left to
 * right. One thing stands at the top of the arc.
 */
export function crownPlaces(count: number): CrownPlace[] {
  return Array.from({ length: count }, (_, index) =>
    crownPlace((index + 0.5) / count),
  );
}

/** The radius in pixels of a streak day's star: larger for a better result. */
export function crownStarRadius(p: number | null): number {
  return p === null ? 2.8 : 2.2 + 3 * clamp(p, 0, 1);
}

/** One of the quiet stars behind the home screen. */
export interface QuietStar {
  /** Fractions of the width and of the height. */
  x: number;
  y: number;
  /** The radius in pixels. */
  size: number;
  alpha: number;
  /** A bright star has a soft halo and two thin rays. */
  bright: boolean;
  phase: number;
  speed: number;
}

/**
 * The stars behind the home screen: sparse dust and a few bright
 * stars, kept apart from each other. They carry no data. The same
 * random source gives the same sky.
 */
export function quietField(
  width: number,
  height: number,
  random: () => number,
): QuietStar[] {
  const dust = clamp(Math.round((width * height) / 2600), 120, 620);
  const stars: QuietStar[] = Array.from({ length: dust }, () => {
    const large = random() < 0.1;
    return {
      x: random(),
      y: random(),
      size: large ? 0.8 + random() * 0.6 : 0.3 + random() * 0.5,
      alpha: large ? 0.45 + random() * 0.4 : 0.12 + random() * 0.36,
      bright: false,
      phase: random() * 6.283,
      speed: 0.3 + random() * 0.9,
    };
  });
  const bright = clamp(Math.round((width * height) / 260000), 3, 6);
  const placed: QuietStar[] = [];
  for (let index = 0; index < bright; index += 1) {
    // Of some places, the one farthest from the bright stars so far.
    let best: [number, number] = [random(), random()];
    let apart = -1;
    for (let attempt = 0; attempt < 12; attempt += 1) {
      const x = random();
      const y = random();
      const nearest = placed.reduce(
        (least, star) => Math.min(least, Math.hypot(star.x - x, star.y - y)),
        2,
      );
      if (nearest > apart) {
        apart = nearest;
        best = [x, y];
      }
    }
    placed.push({
      x: best[0],
      y: best[1],
      size: 1.1 + random() * 1.1,
      alpha: 0.9,
      bright: true,
      phase: random() * 6.283,
      speed: 0.2 + random() * 0.5,
    });
  }
  return [...stars, ...placed];
}

/** Where a faint sketch stands behind the home screen. */
export interface GhostSpot {
  /** The middle of the sketch, as fractions of the screen's first part. */
  x: number;
  y: number;
  /**
   * The size law of Your results (sky/core.ts): 0.14 for the smallest
   * drawing to 1 for the largest. The style sheet turns it into a width.
   */
  share: number;
  /** The tilt in degrees. */
  tilt: number;
}

/** The most a faint sketch tilts to each side, in degrees. */
const GHOST_TILT = 7;

/**
 * A place for a faint sketch with the result `p`. With another sketch
 * on the screen, the place is the one of several that is farthest from
 * it, so two sketches do not stand on each other.
 */
export function ghostSpot(
  p: number,
  random: () => number,
  other: Pick<GhostSpot, "x" | "y"> | null,
): GhostSpot {
  let best: [number, number] = [0.5, 0.5];
  let apart = -1;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const x = lerp(0.12, 0.88, random());
    const y = lerp(0.2, 0.8, random());
    const distance = other === null ? 1 : Math.hypot(other.x - x, other.y - y);
    if (distance > apart) {
      apart = distance;
      best = [x, y];
    }
    if (other === null) {
      break;
    }
  }
  return {
    x: best[0],
    y: best[1],
    share: sizeShare(p),
    tilt: (random() - 0.5) * 2 * GHOST_TILT,
  };
}
