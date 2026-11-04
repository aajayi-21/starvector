/**
 * The one query for the day (spec PL1 §4). The closing screen says the
 * photo comes soon, so the screens read a query that polls while
 * something can change: during a close, around the close time, and when
 * no day is open. The interval is a pure function of the view and the
 * clock, and a hidden tab does not poll.
 */

import type { UseQueryResult } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useApi } from "./client";
import type { DayView } from "./types";

export const POLL_NEAR_MS = 20_000;
export const POLL_FAR_MS = 5 * 60_000;
export const POLL_REVEALED_MS = 60_000;
export const NEAR_CLOSE_MS = 5 * 60_000;

/** How long until the next poll of the day view. */
export function dayPollMs(view: DayView | undefined, now: number): number {
  if (view === undefined) {
    // No day open yet, or a failed read: the next day can start soon.
    return POLL_NEAR_MS;
  }
  switch (view.status) {
    case "closing":
    case "closed":
      return POLL_NEAR_MS;
    case "revealed":
      return POLL_REVEALED_MS;
    case "open": {
      const closesAt =
        typeof view.closes_at === "string"
          ? Date.parse(view.closes_at)
          : Number.NaN;
      if (Number.isNaN(closesAt)) {
        return POLL_FAR_MS;
      }
      // Past the close time counts as near: the timer closes the day at
      // its next firing, and the screen must follow.
      return closesAt - now <= NEAR_CLOSE_MS ? POLL_NEAR_MS : POLL_FAR_MS;
    }
  }
}

/** The screens that read results when the day or its status moves. */
const RESULT_QUERIES = [
  "history",
  "me",
  "leaderboard",
  "skill-board",
  "practice-days",
  "reveal",
];

export function useDayQuery(): UseQueryResult<DayView> {
  const api = useApi();
  const queryClient = useQueryClient();
  const day = useQuery({
    queryKey: ["day"],
    queryFn: () => api.getDay(),
    refetchOnWindowFocus: true,
    refetchInterval: (query) => dayPollMs(query.state.data, Date.now()),
  });
  const moment =
    day.data === undefined ? null : `${day.data.day}:${day.data.status}`;
  const seen = useRef(moment);
  useEffect(() => {
    if (moment !== null && seen.current !== null && moment !== seen.current) {
      for (const key of RESULT_QUERIES) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
    }
    if (moment !== null) {
      seen.current = moment;
    }
  }, [moment, queryClient]);
  return day;
}
