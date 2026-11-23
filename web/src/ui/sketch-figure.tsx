/**
 * A sketch as a constellation in a small picture: its strokes as thin
 * lines and a star at each end and corner (sky/core.ts). The home
 * screen draws it behind the words and beside a day of the streak. It
 * is a picture with no words, so a reader of the page does not get it.
 */

import type { Figure } from "../sky/core";

/** The ink of a stroke with no palette color, on the sky. */
const INK = "#dfe5f5";
/** The radius of a star, as a share of the picture's width. */
const STAR_RADIUS = 0.006;

function pointsOf(points: ReadonlyArray<readonly [number, number]>): string {
  return points.map(([x, y]) => `${x.toFixed(4)},${y.toFixed(4)}`).join(" ");
}

export function SketchFigure(props: {
  figure: Figure;
  className: string;
  style?: React.CSSProperties;
}): React.JSX.Element {
  const { figure } = props;
  return (
    <svg
      className={`sketch-figure ${props.className}`}
      viewBox="0 0 1 1"
      aria-hidden="true"
      style={props.style}
    >
      {figure.lines.map((line, index) => (
        <polyline
          // biome-ignore lint/suspicious/noArrayIndexKey: the strokes of a stored sketch keep their order.
          key={index}
          points={pointsOf(line.points)}
          stroke={line.color ?? INK}
        />
      ))}
      {figure.dots.map(([x, y]) => (
        <circle key={`${x}:${y}`} cx={x} cy={y} r={STAR_RADIUS} />
      ))}
    </svg>
  );
}
