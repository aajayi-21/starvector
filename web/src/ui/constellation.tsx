/**
 * A player's results as a line of stars (the home screen). Each star is
 * one revealed day: its height is the result, from 0% at the foot to
 * 100% at the top, and the dotted line is 50%, what guessing averages.
 * A larger star is a better result, and the best of the row has a halo.
 *
 * The drawing reads revealed days alone, so it says nothing of the
 * open day (I7). It draws what the history holds and judges nothing:
 * no star is marked good or bad, the line of chance is the one
 * reference (I2).
 *
 * An SVG that scales to its column scales its type with it, so the
 * narrow layout gets its own smaller box and the labels stay legible
 * (see ui/narrow.ts).
 */

import type { HistoryDayRow } from "../api/types";
import type { DayNames } from "./day-names";
import { useDayNames } from "./day-names";
import { percentBeaten } from "./format";

/** How many of the latest results the row shows. */
export const CONSTELLATION_DAYS = 7;

interface Box {
  width: number;
  height: number;
  /** The x of the first star and of the last star. */
  left: number;
  right: number;
  /** The y of 100% and of 0%. */
  top: number;
  bottom: number;
  /** Where the line of chance ends; its label follows. */
  chanceEnd: number;
  /** The radius of a star at 0% and at 100%. */
  small: number;
  large: number;
  labelSize: number;
}

const WIDE: Box = {
  width: 720,
  height: 276,
  left: 30,
  right: 612,
  top: 40,
  bottom: 250,
  chanceEnd: 640,
  small: 3,
  large: 6.2,
  labelSize: 15,
};

const NARROW: Box = {
  width: 358,
  height: 176,
  left: 22,
  right: 262,
  top: 30,
  bottom: 150,
  chanceEnd: 284,
  small: 2.8,
  large: 5.4,
  labelSize: 14,
};

/**
 * The faint stars behind the row, as fractions of the box. They are
 * fixed, so the sky is the same on each visit, and they carry no data.
 */
const FIELD: ReadonlyArray<readonly [number, number, number]> = [
  [0.12, 0.14, 1],
  [0.24, 0.3, 1.2],
  [0.36, 0.07, 0.9],
  [0.49, 0.36, 1],
  [0.62, 0.11, 1.1],
  [0.8, 0.3, 0.9],
  [0.96, 0.19, 1.1],
  [0.1, 0.84, 1],
  [0.29, 0.93, 1.1],
  [0.55, 0.9, 0.9],
  [0.76, 0.82, 1.2],
  [0.93, 0.94, 1],
  [0.04, 0.42, 0.8],
  [0.18, 0.6, 0.7],
  [0.3, 0.72, 0.9],
  [0.43, 0.18, 0.7],
  [0.42, 0.78, 1],
  [0.57, 0.62, 0.7],
  [0.7, 0.44, 0.8],
  [0.68, 0.96, 0.8],
  [0.86, 0.06, 0.8],
  [0.84, 0.68, 0.7],
  [0.98, 0.56, 0.9],
  [0.02, 0.04, 0.9],
];

export interface Star {
  day: string;
  p: number;
  x: number;
  y: number;
  r: number;
  /** True for the best result of the row: the one with the halo. */
  best: boolean;
  /**
   * The label sits over the star, not under it. A label is on the side
   * of its star that is away from the line of chance, so the dotted
   * line does not run through the words.
   */
  labelAbove: boolean;
}

/**
 * The stars of the latest results, oldest first. `days` is the history
 * as the server sends it, latest first. Pure, so a test can check the
 * geometry without a browser.
 */
export function starsOf(
  days: ReadonlyArray<Pick<HistoryDayRow, "day" | "p">>,
  box: Pick<
    Box,
    "left" | "right" | "top" | "bottom" | "small" | "large"
  > = WIDE,
): Star[] {
  const shown = days.slice(0, CONSTELLATION_DAYS).reverse();
  const step =
    shown.length <= 1 ? 0 : (box.right - box.left) / (shown.length - 1);
  // One star stands in the middle of the row, not at its left end.
  const start = shown.length === 1 ? (box.left + box.right) / 2 : box.left;
  const best = shown.reduce(
    (top, row, index) => (row.p > (shown[top]?.p ?? -1) ? index : top),
    0,
  );
  return shown.map((row, index) => {
    const y = box.bottom - row.p * (box.bottom - box.top);
    return {
      day: row.day,
      p: row.p,
      x: start + index * step,
      y,
      r: box.small + row.p * (box.large - box.small),
      best: index === best,
      labelAbove: row.p >= 0.5,
    };
  });
}

function describe(stars: ReadonlyArray<Star>, names: DayNames): string {
  const best = stars.find((star) => star.best);
  if (best === undefined) {
    return "Your results appear here as stars after your first day closes.";
  }
  const count =
    stars.length === 1
      ? "Your last result as a star."
      : `Your last ${stars.length} results as a line of stars.`;
  return `${count} A higher star is a better result. ${names.short(best.day)} is the highest at ${percentBeaten(best.p)} percent.`;
}

export function Constellation(props: {
  days: ReadonlyArray<Pick<HistoryDayRow, "day" | "p">>;
  narrow: boolean;
}): React.JSX.Element {
  const names = useDayNames();
  const box = props.narrow ? NARROW : WIDE;
  const stars = starsOf(props.days, box);
  const chanceY = (box.top + box.bottom) / 2;
  return (
    <svg
      className="constellation"
      viewBox={`0 0 ${box.width} ${box.height}`}
      role="img"
      aria-label={describe(stars, names)}
    >
      <g className="constellation-field">
        {FIELD.map(([fx, fy, r], index) => (
          <circle
            key={`${fx}-${fy}`}
            cx={fx * box.width}
            cy={fy * box.height}
            r={r}
            // Each star starts its twinkle at its own point, so no two
            // fade together (styles/home.css).
            style={{ animationDelay: `${-((index * 37) % 80) / 10}s` }}
          />
        ))}
      </g>
      <line
        className="constellation-chance"
        x1={0}
        y1={chanceY}
        x2={box.chanceEnd}
        y2={chanceY}
      />
      <text
        className="constellation-scale"
        x={box.chanceEnd + 11}
        y={chanceY - 3}
      >
        50%
      </text>
      <text
        className="constellation-label"
        x={box.chanceEnd + 11}
        y={chanceY + 14}
        fontSize={box.labelSize}
      >
        guessing
      </text>
      {stars.length < 2 ? null : (
        <polyline
          className="constellation-line"
          points={stars.map((star) => `${star.x},${star.y}`).join(" ")}
        />
      )}
      {stars.map((star) => (
        <g key={star.day}>
          {star.best ? (
            <circle
              className="constellation-halo"
              cx={star.x}
              cy={star.y}
              r={star.r * 2.1}
            />
          ) : null}
          <circle
            className="constellation-star"
            cx={star.x}
            cy={star.y}
            r={star.r}
          />
          <text
            className="constellation-label"
            x={star.x}
            y={
              star.labelAbove
                ? star.y - star.r - 10
                : star.y + star.r + box.labelSize + 5
            }
            fontSize={box.labelSize}
            textAnchor="middle"
          >
            {names.short(star.day)}
          </text>
        </g>
      ))}
    </svg>
  );
}
