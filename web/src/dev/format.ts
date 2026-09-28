/**
 * The console's time formatting. The store, the rollover hour, and the
 * day labels are UTC, so the console shows UTC first and the relative
 * distance second — an operator reading a run record compares it with
 * `closes_at_utc`, not with their own clock.
 */

import { formatRemaining } from "../ui/format";

/** "2026-09-24 22:00 UTC", or "—" for a missing stamp. */
export function utcStamp(iso: string | null | undefined): string {
  if (iso === null || iso === undefined) {
    return "—";
  }
  const moment = new Date(iso);
  if (Number.isNaN(moment.getTime())) {
    return iso;
  }
  return `${moment.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/** "in 3 h 12 min" or "12 min ago", measured from `now` (ms). */
export function relative(iso: string, now: number): string {
  const moment = new Date(iso).getTime();
  if (Number.isNaN(moment)) {
    return "";
  }
  const gap = moment - now;
  if (Math.abs(gap) < 60_000) {
    return "now";
  }
  return gap > 0
    ? `in ${formatRemaining(gap)}`
    : `${formatRemaining(-gap)} ago`;
}

/** The UTC stamp with the distance after it. */
export function stampWithDistance(iso: string | null, now: number): string {
  if (iso === null) {
    return "—";
  }
  return `${utcStamp(iso)} (${relative(iso, now)})`;
}
