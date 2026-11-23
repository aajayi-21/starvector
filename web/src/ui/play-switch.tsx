/**
 * The frame of the Play place: today's sketch and practice are two
 * views of one screen. The days stand in a row (ui/day-stepper.tsx):
 * today is the last one, and a step back is practice on that day. Each
 * view keeps its own path, so the browser's back button works.
 */

import { Link } from "@tanstack/react-router";

import { DayStepper } from "./day-stepper";

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

/** A view of Play that holds a message and no canvas, under the days. */
export function PlayMessage(props: {
  title: string;
  view: "today" | "practice";
  children?: React.ReactNode;
}): React.JSX.Element {
  return (
    <>
      <div className="play-head">
        <DayStepper view={props.view} day={null} />
        <PlayHow />
      </div>
      <section className="play-message">
        <h1>{props.title}</h1>
        {props.children}
      </section>
    </>
  );
}
