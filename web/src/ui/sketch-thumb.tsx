/**
 * A still picture of one sketch, for a row of many (spec SS1 §7.3): the
 * strokes as SVG lines on the drawing ground. A screen with a hundred
 * sketches holds a hundred of these, so it is plain markup and not a
 * canvas: no backing store, no observer, and no effect for each one.
 */

/** The line color of a stroke that has no palette color: the ink. */
const INK = "#eceff4";
/** The line width in the 100-unit box: a line that reads at 150 px. */
const LINE_WIDTH = 1.2;

export interface ThumbStroke {
  points: ReadonlyArray<readonly [number, number]>;
  color?: string | undefined;
}

/** The points of one stroke in the 100-unit box of the picture. */
function linePoints(stroke: ThumbStroke): string {
  const pairs = stroke.points.map(([x, y]) => `${x * 100},${y * 100}`);
  // One point is a dot: a line to itself draws the round end.
  const first = pairs[0];
  return pairs.length === 1 && first !== undefined
    ? `${first} ${first}`
    : pairs.join(" ");
}

export function SketchThumb(props: {
  strokes: ReadonlyArray<ThumbStroke>;
  /** What the picture is, for a reader who cannot see it. */
  label: string;
}): React.JSX.Element {
  return (
    <svg
      className="sketch-thumb"
      viewBox="0 0 100 100"
      role="img"
      aria-label={props.label}
    >
      {props.strokes.map((stroke, index) => (
        <polyline
          // The strokes of a stored sketch do not move: the index is
          // the stroke.
          // biome-ignore lint/suspicious/noArrayIndexKey: see above
          key={index}
          points={linePoints(stroke)}
          fill="none"
          stroke={stroke.color ?? INK}
          strokeWidth={LINE_WIDTH}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      ))}
    </svg>
  );
}
