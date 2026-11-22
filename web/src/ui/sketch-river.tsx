/**
 * The river of a day's sketches (owner design of 2026-11-22): each
 * sketch of the day as a faint constellation, in a row that flows
 * slowly from the right to the left under the podium. A pointer on the
 * row stops it, and a pointer on a sketch brings it up with its name.
 *
 * The river is a picture with nothing to press. Each sketch on it is
 * the sketch alone (spec SS1 §5), so a reader of the page does not get
 * it, and the board below holds each result. Under reduced motion the
 * row stands still and scrolls by hand.
 */

import type { Figure } from "../sky/core";
import { SketchFigure } from "./sketch-figure";

export interface RiverSketch {
  key: string;
  figure: Figure;
  /** The name, and the result where the board shows one. */
  label: string;
}

/**
 * The least count of sketches in one pass of the river. A day with few
 * sketches repeats them, so the row fills a wide screen. A layout
 * number only.
 */
const LEAST_PASS = 12;
/**
 * The most sketches in one pass. A day with more shows the newest of
 * them: the river is a picture of the day and not its record, and a
 * strip of each sketch of a large day would be too wide to move. A
 * layout number only.
 */
const MOST_PASS = 80;
/** The seconds that one sketch adds to a pass, and the least pass. */
const SECONDS_EACH = 4;
const LEAST_SECONDS = 60;

/**
 * One pass of the river: the sketches up to the most, repeated to the
 * least count. The sketches arrive the newest first.
 */
function onePass(sketches: ReadonlyArray<RiverSketch>): RiverSketch[] {
  const kept = sketches.slice(0, MOST_PASS);
  if (kept.length === 0) {
    return [];
  }
  const times = Math.ceil(LEAST_PASS / kept.length);
  return Array.from({ length: times }, () => kept).flat();
}

export function SketchRiver(props: {
  sketches: ReadonlyArray<RiverSketch>;
}): React.JSX.Element | null {
  const pass = onePass(props.sketches);
  if (pass.length === 0) {
    return null;
  }
  const seconds = Math.max(LEAST_SECONDS, pass.length * SECONDS_EACH);
  // Two passes in a row: the track moves by one pass and starts again,
  // so the seam does not show.
  return (
    <div className="river" aria-hidden="true">
      <div
        className="river-track"
        style={{ "--river-seconds": `${seconds}s` } as React.CSSProperties}
      >
        {[0, 1].map((copy) => (
          <div className="river-pass" data-copy={copy} key={copy}>
            {pass.map((sketch, index) => (
              <span
                // A sketch repeats in a pass, so its place is the key.
                // biome-ignore lint/suspicious/noArrayIndexKey: see above
                key={`${sketch.key}:${index}`}
                className="river-item"
              >
                <SketchFigure figure={sketch.figure} className="river-sketch" />
                <span className="river-name">{sketch.label}</span>
              </span>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
