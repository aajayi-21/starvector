/**
 * A player's revealed days as stars on a chart (the Your results
 * screen). Each star is one day: its height is the result, from 0% at
 * the foot to 100% at the top, and the dashed line is 50%, what
 * guessing averages. A larger star is a better result, and the best
 * one has a halo and its date.
 *
 * The chart reads revealed days alone, so it says nothing of the open
 * day (I7). It draws what the history holds and grades nothing: the
 * line of chance is the one reference (I2).
 *
 * An SVG that scales to its column scales its type with it, so the
 * narrow layout gets its own smaller box and the labels stay legible
 * (see ui/narrow.ts).
 */

import type { HistoryDayRow } from "../api/types";
import { formatShortDay, percentBeaten } from "./format";

/**
 * How many of the latest days the chart draws at most. A layout limit
 * only: more stars than this touch each other in the narrow box. The
 * table under the chart holds each day.
 */
export const CHART_DAYS = 60;

interface Box {
  width: number;
  height: number;
  /** The x of the first star and of the last star. */
  left: number;
  right: number;
  /** The y of 100% and of 0%. */
  top: number;
  bottom: number;
  /** Where the scale lines start; the labels of the scale sit before. */
  lineStart: number;
  /** The radius of a star at 0% and at 100%. */
  small: number;
  large: number;
  /** True when the box has room for a word at the end of the chance line. */
  chanceWord: boolean;
}

const WIDE: Box = {
  width: 800,
  height: 304,
  left: 60,
  right: 716,
  top: 20,
  bottom: 270,
  lineStart: 44,
  small: 2.6,
  large: 6,
  chanceWord: true,
};

const NARROW: Box = {
  width: 358,
  height: 212,
  left: 44,
  right: 346,
  top: 16,
  bottom: 176,
  lineStart: 36,
  small: 2,
  large: 4.6,
  chanceWord: false,
};

export interface ChartStar {
  day: string;
  p: number;
  x: number;
  y: number;
  r: number;
  /** True for the best result of the chart: the one with the halo. */
  best: boolean;
}

/**
 * The stars of the latest days, oldest first. `days` is the history as
 * the server sends it, latest first. Pure, so a test can check the
 * geometry without a browser.
 */
export function chartStars(
  days: ReadonlyArray<Pick<HistoryDayRow, "day" | "p">>,
  box: Pick<
    Box,
    "left" | "right" | "top" | "bottom" | "small" | "large"
  > = WIDE,
): ChartStar[] {
  const shown = days.slice(0, CHART_DAYS).reverse();
  const step =
    shown.length <= 1 ? 0 : (box.right - box.left) / (shown.length - 1);
  // One star stands in the middle of the chart, not at its left end.
  const start = shown.length === 1 ? (box.left + box.right) / 2 : box.left;
  const best = shown.reduce(
    (top, row, index) => (row.p > (shown[top]?.p ?? -1) ? index : top),
    0,
  );
  return shown.map((row, index) => ({
    day: row.day,
    p: row.p,
    x: start + index * step,
    y: box.bottom - row.p * (box.bottom - box.top),
    r: box.small + row.p * (box.large - box.small),
    best: index === best,
  }));
}

function describe(stars: ReadonlyArray<ChartStar>, total: number): string {
  const first = stars[0];
  const last = stars[stars.length - 1];
  const best = stars.find((star) => star.best);
  if (first === undefined || last === undefined || best === undefined) {
    return "Your results appear here as stars after your first day closes.";
  }
  const count =
    stars.length === 1
      ? `Your result of ${formatShortDay(first.day)} as a star.`
      : `Your ${stars.length < total ? "latest " : ""}${stars.length} results from ${formatShortDay(first.day)} to ${formatShortDay(last.day)} as a line of stars.`;
  return `${count} A higher star is a better result. The best is ${formatShortDay(best.day)} at ${percentBeaten(best.p)} percent.`;
}

export function ResultsChart(props: {
  days: ReadonlyArray<Pick<HistoryDayRow, "day" | "p">>;
  narrow: boolean;
}): React.JSX.Element {
  const box = props.narrow ? NARROW : WIDE;
  const stars = chartStars(props.days, box);
  const chanceY = (box.top + box.bottom) / 2;
  const first = stars[0];
  const last = stars[stars.length - 1];
  const middle = stars[Math.floor(stars.length / 2)];
  const best = stars.find((star) => star.best);
  // The line of the scale ends at the last star, or at the word of the
  // chance line where the box has one.
  const lineEnd = box.chanceWord ? box.right + 20 : box.width;
  // The date of the best star sits before it, or after it when the
  // star is near the left edge.
  const bestBefore = best !== undefined && best.x > box.left + 110;
  return (
    <svg
      className="results-chart"
      viewBox={`0 0 ${box.width} ${box.height}`}
      role="img"
      aria-label={describe(stars, props.days.length)}
    >
      <g className="results-chart-scale">
        <text x={0} y={box.top + 4}>
          100%
        </text>
        <text x={0} y={chanceY + 4}>
          50%
        </text>
        <text x={0} y={box.bottom + 4}>
          0%
        </text>
      </g>
      <line
        className="results-chart-edge"
        x1={box.lineStart}
        y1={box.top}
        x2={lineEnd}
        y2={box.top}
      />
      <line
        className="results-chart-edge"
        x1={box.lineStart}
        y1={box.bottom}
        x2={lineEnd}
        y2={box.bottom}
      />
      <line
        className="results-chart-chance"
        x1={box.lineStart}
        y1={chanceY}
        x2={lineEnd}
        y2={chanceY}
      />
      {box.chanceWord ? (
        <text
          className="results-chart-label"
          x={box.width}
          y={chanceY + 5}
          textAnchor="end"
        >
          guessing
        </text>
      ) : null}
      {stars.length < 2 ? null : (
        <polyline
          className="results-chart-line"
          points={stars.map((star) => `${star.x},${star.y}`).join(" ")}
        />
      )}
      {best === undefined ? null : (
        <circle
          className="results-chart-halo"
          cx={best.x}
          cy={best.y}
          r={best.r * 2.2}
        />
      )}
      {stars.map((star) => (
        <circle
          key={star.day}
          className="results-chart-star"
          cx={star.x}
          cy={star.y}
          r={star.r}
        />
      ))}
      <g className="results-chart-label">
        {first === undefined ? null : (
          <text
            x={first.x}
            y={box.height - 6}
            textAnchor={stars.length === 1 ? "middle" : "start"}
          >
            {formatShortDay(first.day)}
          </text>
        )}
        {/* The middle date needs room between the two end dates. */}
        {middle === undefined || stars.length < 9 || props.narrow ? null : (
          <text x={middle.x} y={box.height - 6} textAnchor="middle">
            {formatShortDay(middle.day)}
          </text>
        )}
        {last === undefined || stars.length < 2 ? null : (
          <text x={last.x} y={box.height - 6} textAnchor="end">
            {formatShortDay(last.day)}
          </text>
        )}
        {best === undefined || stars.length < 2 ? null : (
          <text
            x={bestBefore ? best.x - best.r - 12 : best.x + best.r + 12}
            y={best.y + 5}
            textAnchor={bestBefore ? "end" : "start"}
          >
            {formatShortDay(best.day)}, {percentBeaten(best.p)}%
          </text>
        )}
      </g>
    </svg>
  );
}
