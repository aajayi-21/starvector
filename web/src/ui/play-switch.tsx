/**
 * The frame of the Play place: the daily challenge and the instant
 * trial are two views of one screen (spec IM1 §8 and §16). A two-way
 * switch moves between them. The daily view also holds the days in a
 * row (ui/day-stepper.tsx): today is the last one, and a step back
 * opens the results of that day. Each view keeps its own path, so the
 * browser's back button works.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../api/client";
import { DayStepper } from "./day-stepper";

export type PlayView = "today" | "instant";

export function PlayFrame(props: {
  children: React.ReactNode;
}): React.JSX.Element {
  return <div className="play">{props.children}</div>;
}

/** The way to how it works: a wide screen has it here and nowhere else. */
export function PlayHow(): React.JSX.Element {
  return (
    <Link to="/how" className="play-how">
      How it works
    </Link>
  );
}

/**
 * The two modes of Play, with the one on the screen marked current. A
 * server with instant trials off has one mode, thus no switch.
 */
export function PlaySwitch(props: {
  view: PlayView;
}): React.JSX.Element | null {
  const api = useApi();
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (about.data?.instant === "off") {
    return null;
  }
  return (
    <nav className="seg play-modes" aria-label="Play modes">
      <Link
        to="/today"
        aria-current={props.view === "today" ? "page" : undefined}
      >
        Daily challenge
      </Link>
      <Link
        to="/instant"
        aria-current={props.view === "instant" ? "page" : undefined}
      >
        Instant trial
      </Link>
    </nav>
  );
}

/** A view of Play that holds a message and no canvas, under the modes. */
export function PlayMessage(props: {
  title: string;
  view: PlayView;
  children?: React.ReactNode;
}): React.JSX.Element {
  return (
    <>
      <div className="play-head">
        <PlaySwitch view={props.view} />
        {props.view === "today" ? <DayStepper /> : null}
        <PlayHow />
      </div>
      <section className="play-message">
        <h1>{props.title}</h1>
        {props.children}
      </section>
    </>
  );
}
