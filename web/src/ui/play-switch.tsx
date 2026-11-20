/**
 * The frame of the Play place: today's sketch and practice are two
 * views of one screen, and a switch at the top center goes between
 * them (owner ruling 2026-11-20). The switch is a pair of links, so
 * each view keeps its own path and the browser's back button works.
 */

import { Link } from "@tanstack/react-router";

const activeProps = { "aria-current": "page" } as const;

export function PlayFrame(props: {
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="play">
      <div className="play-switch">
        <nav className="seg" aria-label="What to play">
          <Link to="/today" activeProps={activeProps}>
            Today
          </Link>
          <Link to="/practice" activeProps={activeProps}>
            Practice
          </Link>
        </nav>
        <Link to="/how" className="play-how">
          How it works
        </Link>
      </div>
      {props.children}
    </div>
  );
}

/** A view of Play that holds a message and no canvas. */
export function PlayMessage(props: {
  title: string;
  children?: React.ReactNode;
}): React.JSX.Element {
  return (
    <section className="play-message">
      <h1>{props.title}</h1>
      {props.children}
    </section>
  );
}
