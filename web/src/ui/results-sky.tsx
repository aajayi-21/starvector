/**
 * The results sky (the Your results screen): each revealed day as its
 * own sketch, drawn as a constellation. The drawings stand scattered
 * over the window with no grid, and each is sized by its result: the
 * larger the drawing, the better the result. A press on one opens that
 * day as words on the sky. A scroll down leaves the sky: each drawing
 * folds into its star, the stars go to their places on the chart of
 * the days, and the numbers follow under it.
 *
 * The sky reads revealed days alone, so it says nothing of the open
 * day (I7). It draws what the history holds and grades nothing: the
 * line of chance on the chart is the one reference (I2), and the words
 * of an opened day state the number against 50%.
 *
 * React renders the nodes here; sky/engine.ts moves them on each frame
 * and sky/core.ts holds the geometry. A sketch arrives after the
 * history does, so a day is a star first and its drawing grows out of
 * the star.
 */

import {
  ArrowRight,
  CaretDown,
  CaretLeft,
  CaretRight,
  X,
} from "@phosphor-icons/react";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import type { HistoryDayRow, SketchStroke } from "../api/types";
import { ReplayCanvas } from "../sketch/canvas";
import { type Figure, figureOf, SKY_DAYS, seedOf } from "../sky/core";
import { createSky, type Sky } from "../sky/engine";
import { ChanceMeter } from "./chance-meter";
import { useDayNames } from "./day-names";
import { ordinal, percentBeaten } from "./format";

/**
 * The sketch of a day: its strokes, null for a send with no sketch to
 * show, and undefined while it loads.
 */
export type DaySketch = ReadonlyArray<SketchStroke> | null | undefined;

/** The ink of a stroke with no palette color, on the sky. */
const INK = "#dfe5f5";

function pointsOf(points: ReadonlyArray<readonly [number, number]>): string {
  return points.map(([x, y]) => `${x.toFixed(4)},${y.toFixed(4)}`).join(" ");
}

/** The figures of the days, kept so a render does not draw them again. */
function useFigures(
  days: ReadonlyArray<HistoryDayRow>,
  sketchOf: (day: string) => DaySketch,
): Array<Figure | null> {
  const kept = useRef(
    new Map<string, { sketch: DaySketch; figure: Figure | null }>(),
  );
  return days.map((row) => {
    const sketch = sketchOf(row.day);
    const held = kept.current.get(row.day);
    if (held !== undefined && held.sketch === sketch) {
      return held.figure;
    }
    const figure = sketch ? figureOf(sketch) : null;
    kept.current.set(row.day, { sketch, figure });
    return figure;
  });
}

export function ResultsSky(props: {
  /** The history as the server sends it, the latest day first. */
  days: ReadonlyArray<HistoryDayRow>;
  /** The sketch of a day, by its label. */
  sketchOf: (day: string) => DaySketch;
  /** The player's name: the same player gets the same sky. */
  player: string;
}): React.JSX.Element {
  const names = useDayNames();
  // Oldest first, as the chart runs.
  const shown = useMemo(
    () => props.days.slice(0, SKY_DAYS).reverse(),
    [props.days],
  );
  const figures = useFigures(shown, props.sketchOf);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const skyRef = useRef<Sky | null>(null);
  const [picked, setPicked] = useState<number | null>(null);

  // The engine holds the places of the days. A change of the results
  // is a new sky; a change of a name or of a sketch is not.
  const results = shown.map((row) => `${row.day}:${row.p}`).join(" ");
  // biome-ignore lint/correctness/useExhaustiveDependencies: `results` is the content of `shown`, and the sky is built again for a change of content alone.
  useEffect(() => {
    const stage = stageRef.current;
    if (stage === null) {
      return;
    }
    setPicked(null);
    const sky = createSky(
      stage,
      shown.map((row) => ({ p: row.p })),
      seedOf(props.player),
      { onPick: setPicked },
    );
    skyRef.current = sky;
    return () => {
      sky.dispose();
      skyRef.current = null;
    };
  }, [results, props.player]);

  const drawn = figures.map((figure) => (figure === null ? "0" : "1")).join("");
  // biome-ignore lint/correctness/useExhaustiveDependencies: `drawn` says which days have a drawing; the engine reads the new nodes.
  useEffect(() => {
    skyRef.current?.syncFigures();
  }, [drawn]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: a new sky has no chosen day until this effect tells it.
  useEffect(() => {
    skyRef.current?.setPicked(picked);
  }, [picked, results]);

  const first = shown[0];
  const last = shown[shown.length - 1];
  const middle = shown[Math.floor(shown.length / 2)];
  const best = shown.reduce<HistoryDayRow | undefined>(
    (top, row) => (top === undefined || row.p > top.p ? row : top),
    undefined,
  );
  const more = props.days.length > shown.length;
  const open = picked === null ? undefined : shown[picked];
  const sketch = open === undefined ? undefined : props.sketchOf(open.day);

  return (
    <section
      className="sky-space"
      aria-label="Your results as a sky of your sketches"
    >
      <div className="sky-stage" ref={stageRef}>
        {/* The title comes first for a reader of the page; the layers of
            the sky take their order from styles/sky.css. */}
        <header className="sky-head">
          <h1 className="h-display">Your results</h1>
          <div className="sky-caps">
            <p data-sky="cap-sky">
              {more
                ? `The sketches of your latest ${SKY_DAYS} days, each as its own constellation.`
                : "Each day's sketch, as its own constellation."}{" "}
              The larger the drawing, the better the result.
            </p>
            <p data-sky="cap-chart">
              {more
                ? `Each star is one of your latest ${SKY_DAYS} days, newest on the right.`
                : "Each star is one day, newest on the right."}{" "}
              A higher star is a better result. The dashed line is 50% — what
              guessing averages.
            </p>
          </div>
        </header>
        {/* The faint stars behind: a picture with nothing to read. */}
        <canvas className="sky-field" data-sky="field" />
        <svg className="sky-lines" aria-hidden="true">
          <polyline className="sky-thread" data-sky="thread" />
          <g className="sky-chance" data-sky="chance">
            <line data-sky="chance-line" />
            <text data-sky="scale-middle">50%</text>
            <text
              className="sky-atlas sky-wide"
              data-sky="chance-word"
              textAnchor="end"
            >
              guessing
            </text>
          </g>
          <g className="sky-frame" data-sky="frame">
            <line data-sky="edge-top" />
            <line data-sky="edge-foot" />
            <text data-sky="scale-top">100%</text>
            <text data-sky="scale-foot">0%</text>
            <text className="sky-atlas" data-sky="date-first">
              {first === undefined ? "" : names.short(first.day)}
            </text>
            <text
              className="sky-atlas sky-wide"
              data-sky="date-middle"
              textAnchor="middle"
            >
              {/* The middle date needs room between the two end dates. */}
              {middle === undefined || shown.length < 9
                ? ""
                : names.short(middle.day)}
            </text>
            <text className="sky-atlas" data-sky="date-last" textAnchor="end">
              {last === undefined || shown.length < 2
                ? ""
                : names.short(last.day)}
            </text>
            <text className="sky-atlas" data-sky="date-best">
              {best === undefined || shown.length < 2
                ? ""
                : `${names.short(best.day)}, ${percentBeaten(best.p)}%`}
            </text>
          </g>
          <line className="sky-leader" data-sky="leader" />
        </svg>
        <div className="sky-figs" data-sky="figs" aria-hidden="true">
          {shown.map((row, index) => {
            const figure = figures[index];
            if (figure === null || figure === undefined) {
              return null;
            }
            return (
              <svg
                key={row.day}
                className="sky-fig"
                viewBox="0 0 1 1"
                aria-hidden="true"
                data-sky-fig=""
                data-index={index}
                data-ax={figure.anchor[0]}
                data-ay={figure.anchor[1]}
              >
                {figure.lines.map((line, lineIndex) => (
                  <polyline
                    // biome-ignore lint/suspicious/noArrayIndexKey: the strokes of a stored sketch keep their order.
                    key={lineIndex}
                    points={pointsOf(line.points)}
                    stroke={line.color ?? INK}
                  />
                ))}
                {/* The first star is the day's own button, over the drawing. */}
                {figure.dots.slice(1).map(([x, y]) => (
                  <circle key={`${x}:${y}`} cx={x} cy={y} />
                ))}
              </svg>
            );
          })}
        </div>
        <span className="sky-label" data-sky="label" aria-hidden="true" />
        {/* biome-ignore lint/a11y/useSemanticElements: a fieldset draws a box, and nothing here has one. */}
        <div
          className="sky-stars"
          data-sky="stars"
          role="group"
          aria-label="Your days, the oldest first"
        >
          {shown.map((row, index) => (
            <button
              key={row.day}
              type="button"
              className={row === best ? "sky-star is-best" : "sky-star"}
              data-sky-star=""
              data-index={index}
              data-hover={`${names.short(row.day)} · ${percentBeaten(row.p)}%`}
              aria-label={`${names.long(row.day)}: ${percentBeaten(row.p)} percent`}
              aria-pressed={picked === index}
            >
              <span className="sky-star-dot" />
            </button>
          ))}
        </div>
        <div className="sky-scrim" aria-hidden="true" />
        <div className="sky-veil" aria-hidden="true" />
        {/* The opened day, said one time for a reader who does not see it. */}
        <p className="visually-hidden" role="status">
          {open === undefined
            ? ""
            : `${names.long(open.day)}: you beat ${percentBeaten(open.p)}% of the photos.`}
        </p>
        <div className="sky-dock">
          <aside
            className="sky-plate"
            data-sky="plate"
            aria-label="The chosen day"
          >
            {open === undefined || picked === null ? null : (
              <>
                <div className="sky-plate-top">
                  <p className="eyebrow">
                    <time dateTime={open.day}>{names.long(open.day)}</time>
                    <span className="sky-code">{open.trial_code}</span>
                  </p>
                  <button
                    type="button"
                    className="btn btn-icon"
                    aria-label="Close this day"
                    onClick={() => setPicked(null)}
                  >
                    <X size={18} aria-hidden="true" />
                  </button>
                </div>
                <p className="sky-plate-lead">
                  You beat <strong>{percentBeaten(open.p)}%</strong> of the
                  photos
                </p>
                <ChanceMeter p={open.p} />
                <div className="sky-plate-row">
                  <div className="picture-frame is-sketch sky-plate-sketch">
                    {sketch === undefined ? null : sketch === null ||
                      sketch.length === 0 ? (
                      <p className="small picture-empty">No sketch this day.</p>
                    ) : (
                      <ReplayCanvas strokes={sketch} />
                    )}
                  </div>
                  <div className="sky-plate-side">
                    <p className="muted">
                      {ordinal(open.target_rank)} of {open.decoy_count + 1}{" "}
                      photos
                    </p>
                    <Link
                      to="/reveal"
                      search={{ day: open.day }}
                      className="foot-link"
                    >
                      Photo and details
                      <ArrowRight size={18} aria-hidden="true" />
                    </Link>
                  </div>
                </div>
                <div className="sky-plate-steps">
                  <button
                    type="button"
                    className="btn btn-icon"
                    aria-label="The day before"
                    disabled={picked === 0}
                    onClick={() => setPicked(picked - 1)}
                  >
                    <CaretLeft size={18} aria-hidden="true" />
                  </button>
                  <button
                    type="button"
                    className="btn btn-icon"
                    aria-label="The day after"
                    disabled={picked === shown.length - 1}
                    onClick={() => setPicked(picked + 1)}
                  >
                    <CaretRight size={18} aria-hidden="true" />
                  </button>
                  <span className="subtle tiny">
                    Day {picked + 1} of {shown.length}
                  </span>
                </div>
              </>
            )}
          </aside>
        </div>
        <p className="sky-cue" data-sky="cue">
          <span>Press a sketch to open its day</span>
          <span>Scroll down for the numbers</span>
          <CaretDown size={18} aria-hidden="true" />
        </p>
      </div>
    </section>
  );
}
