/**
 * The start report (spec R1 §4): the drawing screen tells the server
 * that it shows the open day, and the server records the first report
 * of each player and each day with its own clock.
 *
 * One report goes out for each player and each day in one page load.
 * The memory is tied to the Api object, which the app makes one time
 * for a page load, thus a second render, a refocus, and a second visit
 * of the drawing screen send nothing.
 *
 * A report that fails is not sent again. A late report gives a start
 * time after the true one, and a wrong time that looks correct is
 * worse than no time: the public database then holds no duration for
 * that send (spec R1 §6, `seconds_from_start`).
 */

import type { DayApi } from "./client";

const reported = new WeakMap<DayApi, Set<string>>();

/** Send the start report for this player and day, one time. */
export function reportDayStart(api: DayApi, player: string, day: string): void {
  let seen = reported.get(api);
  if (seen === undefined) {
    seen = new Set<string>();
    reported.set(api, seen);
  }
  // A username holds no space (spec A2 §4.1), thus the key is exact.
  const key = `${player} ${day}`;
  if (seen.has(key)) {
    return;
  }
  seen.add(key);
  // The drawing screen does not wait for the answer and shows no
  // error of this call: the record is not a part of the send.
  api.startDay().catch(() => undefined);
}
