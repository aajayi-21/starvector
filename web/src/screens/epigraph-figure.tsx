/**
 * The epigraph under the home greeting (spec H1 §5). It starts on a
 * random epigraph and moves to a different one at an interval. The
 * interval stops while the tab is hidden and when the player asks
 * for reduced motion. The figure keeps a minimum height, so a change
 * does not move the page.
 */

import { useEffect, useState } from "react";

import { ResolveText } from "../ui/resolve-text";
import type { Epigraph } from "./epigraphs";
import { nextIndex, type Random } from "./greeting";
import { EPIGRAPH_MS } from "./greeting-constants";

function prefersReducedMotion(): boolean {
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
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

  // biome-ignore lint/correctness/useExhaustiveDependencies: `random` is a stable source, not a value that moves
  useEffect(() => {
    if (epigraphs.length < 2 || prefersReducedMotion()) {
      return;
    }
    const timer = window.setInterval(() => {
      if (document.visibilityState === "hidden") {
        return;
      }
      setIndex((current) => nextIndex(current, epigraphs.length, random));
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [epigraphs.length, intervalMs]);

  const epigraph = epigraphs[index];
  if (epigraph === undefined) {
    return null;
  }
  return (
    <figure className="epigraph" data-testid="epigraph">
      <blockquote key={index}>
        <ResolveText text={epigraph.text} random={random} />
      </blockquote>
      <figcaption>
        {epigraph.author}, <cite>{epigraph.work}</cite>
      </figcaption>
    </figure>
  );
}
