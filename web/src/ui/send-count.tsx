/**
 * The send count of a day (spec H1 §3), as the control that opens the
 * sketches of that day (spec SS1 §7.3). With no send there is nothing
 * to open, and the count stays text.
 */

import { CaretRight } from "@phosphor-icons/react";
import { Link } from "@tanstack/react-router";

import type { DayView } from "../api/types";
import { sendCountText } from "./format";

export function SendCount(props: {
  day: Pick<DayView, "day" | "sends" | "status">;
  className: string;
  testId: string;
}): React.JSX.Element {
  const { day } = props;
  const text = sendCountText(day.sends, day.status === "open");
  return (
    <p className={props.className} data-testid={props.testId}>
      {day.sends === 0 ? (
        text
      ) : (
        <Link to="/sends" search={{ day: day.day }} className="count-link">
          {text}
          <CaretRight size={14} aria-hidden="true" />
        </Link>
      )}
    </p>
  );
}

/** What the sends screen can show for a day (spec SS1 §4). */
export type SendsGate = "open" | "send-first" | "after-reveal";

/**
 * Send, then see, read from the day view alone, so a player with no
 * send asks the server for nothing. `view` is the latest day. An
 * earlier day is revealed: the server opens a day after the reveal of
 * the day before it.
 */
export function sendsGate(
  view: Pick<DayView, "day" | "status" | "submitted">,
  day: string,
): SendsGate {
  if (day !== view.day || view.status === "revealed" || view.submitted) {
    return "open";
  }
  return view.status === "open" ? "send-first" : "after-reveal";
}
