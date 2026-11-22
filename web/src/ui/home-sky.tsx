/**
 * The sky behind the home screen: quiet stars, and the player's own
 * past sketches as faint constellations. One or two sketches show at a
 * time, each larger for a better result (the size law of Your results),
 * and each comes and goes slowly behind the words.
 *
 * The sky is a picture with nothing to read or press: a reader of the
 * page does not get it. It draws revealed days alone (I7) and grades
 * nothing (I2). Under reduced motion one sketch stands still.
 */

import { useEffect, useRef, useState } from "react";

import type { Figure } from "../sky/core";
import { randomOf } from "../sky/core";
import { type GhostSpot, ghostSpot } from "../sky/home";
import { createQuietSky } from "../sky/quiet";
import { SketchFigure } from "./sketch-figure";

/** One revealed day's sketch, ready to draw. */
export interface SkySketch {
  day: string;
  p: number;
  figure: Figure;
}

/** How long a sketch takes to come or go; styles/home.css has the same time. */
const FADE_MS = 4500;
/** How long a sketch stays, and how much that time varies. */
const HOLD_MS = 12000;
const HOLD_SPREAD_MS = 6000;
/** The second sketch starts this long after the first. */
const SECOND_AFTER_MS = 7000;
/** With no sketch to show yet, how long until the next look. */
const RETRY_MS = 2000;

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

interface Ghost {
  key: string;
  day: string;
  spot: GhostSpot;
  on: boolean;
}

/**
 * The sketches on the sky now. `count` places take turns through the
 * sketches; a place waits while there is no sketch for it.
 */
function useGhosts(
  sketches: ReadonlyArray<SkySketch>,
  seed: number,
  count: number,
): Ghost[] {
  const [ghosts, setGhosts] = useState<Ghost[]>([]);
  // The sketches arrive one by one; the turns read the list as it is.
  const latest = useRef(sketches);
  latest.current = sketches;

  useEffect(() => {
    const still =
      typeof window.matchMedia === "function" &&
      window.matchMedia(REDUCED_MOTION).matches;
    const random = randomOf(seed);
    const live: Array<Ghost | null> = Array.from({ length: count }, () => null);
    const timers = new Set<number>();
    let next = 0;
    let serial = 0;
    let stopped = false;
    const later = (run: () => void, ms: number): void => {
      const timer = window.setTimeout(() => {
        timers.delete(timer);
        if (!stopped) {
          run();
        }
      }, ms);
      timers.add(timer);
    };
    const publish = (): void =>
      setGhosts(live.filter((ghost): ghost is Ghost => ghost !== null));

    const show = (place: number): void => {
      const list = latest.current;
      const others = live.filter((_each, index) => index !== place);
      // The next sketch in turn that is not on the sky now.
      let sketch: SkySketch | undefined;
      for (let attempt = 0; attempt < list.length; attempt += 1) {
        const candidate = list[next % list.length];
        next += 1;
        if (
          candidate !== undefined &&
          !others.some((ghost) => ghost?.day === candidate.day)
        ) {
          sketch = candidate;
          break;
        }
      }
      if (sketch === undefined) {
        live[place] = null;
        publish();
        later(() => show(place), RETRY_MS);
        return;
      }
      serial += 1;
      const other = others.find((ghost) => ghost !== null) ?? null;
      const ghost: Ghost = {
        key: `${place}:${serial}`,
        day: sketch.day,
        spot: ghostSpot(sketch.p, random, other?.spot ?? null),
        on: false,
      };
      live[place] = ghost;
      publish();
      // One step later, so the style has a start to fade from.
      later(() => {
        live[place] = { ...ghost, on: true };
        publish();
      }, 60);
      if (still) {
        return;
      }
      later(
        () => {
          live[place] = { ...ghost, on: false };
          publish();
          later(() => show(place), FADE_MS + 600);
        },
        FADE_MS + HOLD_MS + random() * HOLD_SPREAD_MS,
      );
    };

    show(0);
    for (let place = 1; place < count; place += 1) {
      if (still) {
        break;
      }
      later(() => show(place), SECOND_AFTER_MS * place);
    }
    return () => {
      stopped = true;
      for (const timer of timers) {
        window.clearTimeout(timer);
      }
    };
  }, [seed, count]);

  return ghosts;
}

export function HomeSky(props: {
  /** The same player gets the same sky. */
  seed: number;
  /** The sketches of the player's latest revealed days. */
  sketches: ReadonlyArray<SkySketch>;
  /** A narrow screen has room for one sketch at a time. */
  narrow: boolean;
}): React.JSX.Element {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const ghosts = useGhosts(props.sketches, props.seed, props.narrow ? 1 : 2);

  useEffect(() => {
    if (canvas.current === null) {
      return;
    }
    const sky = createQuietSky(canvas.current, props.seed);
    return () => sky.dispose();
  }, [props.seed]);

  return (
    <div className="home-sky" aria-hidden="true">
      <canvas className="home-sky-field" ref={canvas} />
      {ghosts.map((ghost) => {
        const sketch = props.sketches.find((each) => each.day === ghost.day);
        if (sketch === undefined) {
          return null;
        }
        return (
          <SketchFigure
            key={ghost.key}
            figure={sketch.figure}
            className={ghost.on ? "home-ghost is-on" : "home-ghost"}
            style={
              {
                left: `${(ghost.spot.x * 100).toFixed(1)}%`,
                top: `${(ghost.spot.y * 100).toFixed(1)}%`,
                "--ghost-share": ghost.spot.share.toFixed(3),
                "--ghost-tilt": `${ghost.spot.tilt.toFixed(1)}deg`,
              } as React.CSSProperties
            }
          />
        );
      })}
    </div>
  );
}
