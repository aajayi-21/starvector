/**
 * The epigraph under the home greeting (spec H1 §5). It starts on a
 * random epigraph and moves to a different one at an interval.
 *
 * The rotation stops while the tab is hidden, while the pointer or the
 * focus is on the figure, when the player presses pause, and when the
 * player asks for reduced motion — read live, not only at mount. The
 * pause control meets WCAG 2.2.2 (pause, stop, hide) for content that
 * moves by itself for more than five seconds.
 *
 * Each epigraph also renders, hidden, in the same grid cell, so the
 * frame is as tall as the tallest one at the current width and a change
 * never moves the page.
 */

import { Pause, Play } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { ResolveText } from "../ui/resolve-text";
import type { Epigraph } from "./epigraphs";
import { nextIndex, type Random } from "./greeting";
import { EPIGRAPH_MS } from "./greeting-constants";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED_MOTION).matches
  );
}

/** The reduced-motion setting, kept current when the player changes it. */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      return;
    }
    const query = window.matchMedia(REDUCED_MOTION);
    const update = (): void => setReduced(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return reduced;
}

const STILL: Random = () => 0;

/**
 * True while the pointer or the focus is on the element. The hold is
 * passive, not a control, so it listens through a ref and the element
 * keeps no handler props.
 */
function useHeld(ref: React.RefObject<HTMLDivElement | null>): boolean {
  const [held, setHeld] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (element === null) {
      return;
    }
    const hold = (): void => setHeld(true);
    const release = (): void => setHeld(false);
    const pairs = [
      ["mouseenter", hold],
      ["mouseleave", release],
      ["focusin", hold],
      ["focusout", release],
    ] as const;
    for (const [name, fn] of pairs) {
      element.addEventListener(name, fn);
    }
    return () => {
      for (const [name, fn] of pairs) {
        element.removeEventListener(name, fn);
      }
    };
  }, [ref]);
  return held;
}

export function EpigraphFigure(props: {
  epigraphs: readonly Epigraph[];
  random?: Random;
  intervalMs?: number;
}): React.JSX.Element | null {
  const { epigraphs, random = Math.random, intervalMs = EPIGRAPH_MS } = props;
  const [index, setIndex] = useState(() =>
    Math.floor(random() * epigraphs.length),
  );
  const [paused, setPaused] = useState(false);
  const frame = useRef<HTMLDivElement>(null);
  const held = useHeld(frame);
  const reduced = useReducedMotion();
  const rotates = epigraphs.length >= 2 && !reduced;
  const stopped = !rotates || paused || held;

  // biome-ignore lint/correctness/useExhaustiveDependencies: `random` is a stable source, not a value that moves
  useEffect(() => {
    if (stopped) {
      return;
    }
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") {
        return;
      }
      setIndex((current) => nextIndex(current, epigraphs.length, random));
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [epigraphs.length, intervalMs, stopped]);

  const epigraph = epigraphs[index];
  if (epigraph === undefined) {
    return null;
  }
  return (
    <div ref={frame} className="epigraph-frame">
      {epigraphs.map((each, eachIndex) => (
        <div
          // The set does not reorder: the key is the position.
          // biome-ignore lint/suspicious/noArrayIndexKey: see above
          key={eachIndex}
          className="epigraph-sizer"
          aria-hidden="true"
        >
          <div className="epigraph-text">
            <ResolveText text={each.text} random={STILL} />
          </div>
          <div className="epigraph-cite">
            {each.author}, <cite>{each.work}</cite>
          </div>
        </div>
      ))}
      <figure className="epigraph" data-testid="epigraph">
        <blockquote key={index} className="epigraph-text">
          <ResolveText text={epigraph.text} random={random} />
        </blockquote>
        <figcaption className="epigraph-cite">
          {epigraph.author}, <cite>{epigraph.work}</cite>
        </figcaption>
      </figure>
      {rotates ? (
        <button
          type="button"
          className="btn btn-ghost btn-icon epigraph-toggle"
          aria-label={paused ? "Play the epigraphs" : "Pause the epigraphs"}
          onClick={() => setPaused((value) => !value)}
        >
          {paused ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
        </button>
      ) : null}
    </div>
  );
}
