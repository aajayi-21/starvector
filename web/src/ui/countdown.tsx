/**
 * The close countdown. A fixed one-minute tick (spec W1 §8): the
 * cadence depends on nothing the server sends.
 */

import { Clock } from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { formatRemaining } from "./format";

export function useNow(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/** Milliseconds until the close, or null when unknown or past. */
export function useRemaining(
  closesAt: string | null | undefined,
): number | null {
  const now = useNow();
  if (typeof closesAt !== "string") {
    return null;
  }
  const remaining = Date.parse(closesAt) - now;
  return Number.isNaN(remaining) || remaining <= 0 ? null : remaining;
}

/** "Closes in 5 h 12 min", or null when the time is unknown or past. */
export function ClosesIn(props: {
  closesAt: string | null | undefined;
  prefix?: string;
}): React.JSX.Element | null {
  const remaining = useRemaining(props.closesAt);
  if (remaining === null) {
    return null;
  }
  return (
    <span>
      {props.prefix ?? "Closes in"} {formatRemaining(remaining)}
    </span>
  );
}

/** The countdown as a badge, or nothing when there is no countdown. */
export function ClosesInBadge(props: {
  closesAt: string | null | undefined;
}): React.JSX.Element | null {
  const remaining = useRemaining(props.closesAt);
  if (remaining === null) {
    return null;
  }
  return (
    <span className="badge">
      <Clock size={16} aria-hidden="true" />
      Closes in {formatRemaining(remaining)}
    </span>
  );
}
