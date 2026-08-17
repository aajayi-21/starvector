/**
 * The skill board's pure core (spec M1 §9).
 *
 * jsdom has no layout and the end-to-end board is correctly gated,
 * so nothing automated ever measures the rendered chart. The
 * geometry therefore lives here as plain functions over plain
 * numbers, returning fractions of the plot box rather than pixels,
 * and the unit tests assert the fractions. The SVG that consumes
 * them holds no arithmetic of its own.
 *
 * Two choices are load-bearing and neither is cosmetic.
 *
 * **The chart plots `y`, the raw estimate — never `shrunk`.** The
 * shrunk value is pulled toward the fitted centre of the very
 * population the band is derived from, so plotting it would put
 * every point inside the band by construction and destroy the one
 * thing the chart is for.
 *
 * **The x axis is logarithmic in the trial count.** A linear axis
 * piles every low-trial player against the left edge, which is
 * exactly the run a reader needs to see spread out. The unit test
 * pins equal spacing for 3, 30 and 300 so a later "simplification"
 * to a linear axis fails loudly.
 *
 * Displayed numbers are skill numbers throughout: the axis labels
 * and the band read `exp(...)` of the log scale, so 1.000 is
 * chance everywhere and a player never meets a log value.
 */

import type { BaselineBandPoint, SkillBoardRow } from "../api/types";

/** Candidate trial-count gridlines. Labels, not statistics. */
const TRIAL_TICKS = [1, 3, 10, 30, 100, 300, 1000, 3000];

/** Candidate skill-number gridlines. 1.0 is chance, so it leads. */
const SKILL_TICKS = [1, 0.5, 0.67, 0.8, 1.25, 1.5, 2, 3, 0.33, 4];

/** How many skill gridlines to draw at most. */
const SKILL_TICK_LIMIT = 5;

/** Padding added to the plotted range, as a share of its height. */
const RANGE_PADDING = 0.08;

export interface FunnelPoint {
  player: string;
  display_name: string;
  n: number;
  /** The skill number, for the point's own label. */
  theta: number;
  eligible: boolean;
  self: boolean;
  /** Fractions of the plot box. y runs down, as SVG does. */
  x: number;
  y: number;
}

export interface FunnelBandPoint {
  n: number;
  x: number;
  /** The band edges as fractions, already ordered top then bottom. */
  top: number;
  bottom: number;
}

export interface AxisTick {
  value: number;
  /** A fraction of the plot box along that axis. */
  position: number;
  label: string;
}

export interface FunnelGeometry {
  points: FunnelPoint[];
  band: FunnelBandPoint[];
  trialTicks: AxisTick[];
  skillTicks: AxisTick[];
  /** True when there is nothing to draw. The caller renders copy. */
  empty: boolean;
}

interface Range {
  low: number;
  high: number;
}

/** Where `value` sits in `range`, as a fraction. Flat means centred. */
function fraction(value: number, range: Range): number {
  const span = range.high - range.low;
  return span === 0 ? 0.5 : (value - range.low) / span;
}

function padded(values: number[]): Range {
  const low = Math.min(...values);
  const high = Math.max(...values);
  const pad = (high - low) * RANGE_PADDING;
  return pad === 0
    ? { low: low - 0.5, high: high + 0.5 }
    : {
        low: low - pad,
        high: high + pad,
      };
}

/**
 * The chart's geometry: dots, the no-skill band, and both axes.
 *
 * `rows` is every player the board serves and `band` is the
 * server's ladder — the client never derives a band, because the
 * limits are a Layer 9 formula and a second copy of it in a
 * browser is what the wire types forbid.
 *
 * `self` is the caller's store key, which is unique; display names
 * are not, so nothing here compares on one.
 */
export function funnelGeometry(
  rows: SkillBoardRow[],
  band: BaselineBandPoint[],
  self: string,
): FunnelGeometry {
  if (rows.length === 0) {
    return {
      points: [],
      band: [],
      trialTicks: [],
      skillTicks: [],
      empty: true,
    };
  }
  const ordered = [...band].sort((a, b) => a.n - b.n);
  const counts = [
    ...rows.map((row) => row.n),
    ...ordered.map((point) => point.n),
  ];
  // Logarithmic in the trial count. Guard the domain at 1: a trial
  // count is never zero, but log(0) would silently poison the axis.
  const trials: Range = {
    low: Math.log(Math.max(1, Math.min(...counts))),
    high: Math.log(Math.max(1, Math.max(...counts))),
  };
  const skill = padded([
    ...rows.map((row) => row.y),
    ...ordered.flatMap((point) => [point.low, point.high]),
  ]);
  const atTrials = (n: number): number =>
    fraction(Math.log(Math.max(1, n)), trials);
  // y runs down in SVG, so a high skill number sits near zero.
  const atSkill = (value: number): number => 1 - fraction(value, skill);
  return {
    points: rows.map((row) => ({
      player: row.player,
      display_name: row.display_name,
      n: row.n,
      theta: row.theta,
      eligible: row.eligible,
      self: row.player === self,
      x: atTrials(row.n),
      y: atSkill(row.y),
    })),
    band: ordered.map((point) => ({
      n: point.n,
      x: atTrials(point.n),
      top: atSkill(point.high),
      bottom: atSkill(point.low),
    })),
    trialTicks: TRIAL_TICKS.filter(
      (n) => Math.log(n) >= trials.low && Math.log(n) <= trials.high,
    ).map((n) => ({
      value: n,
      position: atTrials(n),
      label: String(n),
    })),
    skillTicks: SKILL_TICKS.filter(
      (value) => Math.log(value) >= skill.low && Math.log(value) <= skill.high,
    )
      .slice(0, SKILL_TICK_LIMIT)
      .sort((a, b) => a - b)
      .map((value) => ({
        value,
        position: atSkill(Math.log(value)),
        label: value.toFixed(2),
      })),
    empty: false,
  };
}

export interface BoardSlice {
  /** The ranked run, at most `limit` rows. */
  shown: SkillBoardRow[];
  /** The caller's row when the cut left it out. Never duplicated. */
  pinned: SkillBoardRow | null;
  /** Every ranked player, so the screen can say what it cut. */
  total: number;
}

/**
 * The ranked table's rows: the head of the board plus the caller.
 *
 * Only eligible players are ranked, so only they appear here — the
 * chart is where everybody else is. The caller is pinned below the
 * cut when their rank falls outside it, and is never shown twice.
 *
 * Rows arrive ordered by expected rank, which is what the server
 * sorts by, so this takes the head and does not sort again.
 */
export function boardSlice(
  rows: SkillBoardRow[],
  self: string,
  limit: number,
): BoardSlice {
  const ranked = rows.filter((row) => row.eligible);
  const shown = ranked.slice(0, limit);
  const own = ranked.find((row) => row.player === self) ?? null;
  const pinned = own !== null && !shown.includes(own) ? own : null;
  return { shown, pinned, total: ranked.length };
}
