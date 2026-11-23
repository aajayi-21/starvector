/**
 * The name of a day in the reader's own zone (spec BR1 §3.3, note of
 * 2026-11-20). A day label is a UTC date and stays the identifier in
 * each address, API call, file name, and the public database. On a
 * screen, an earlier day reads as the local calendar date on which it
 * started: the day that runs from 4 PM Friday to 4 PM Saturday in
 * Los Angeles is "Fri, Nov 20". The day in play shows no calendar
 * date: its screens say "today" and name the close.
 *
 * The start of a day comes from ui/day-calendar.ts, which mirrors
 * service/schedule.py. The naming rule is in this one file, so a change
 * of the rule is one edit.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { useApi } from "../api/client";
import { dayStart, labelMidnight } from "./day-calendar";
import { formatDay, formatShortDay } from "./format";

export interface DayNames {
  /** "2026-11-21" → "Fri, Nov 20". */
  long(label: string): string;
  /** "2026-11-21" → "Nov 20". */
  short(label: string): string;
  /** "2026-11-21" → "F", the first letter of the weekday. */
  weekdayLetter(label: string): string;
  /**
   * The calendar date on which the day started, in the reader's zone:
   * the date its names say. Null for text that is not a label.
   */
  calendarDate(label: string): CalendarDate | null;
}

/** A date of a calendar: the month counts from 0, as in `Date`. */
export interface CalendarDate {
  year: number;
  month: number;
  date: number;
}

export interface DayNameOptions {
  /** A named zone, for a test. The default is the reader's own zone. */
  timeZone?: string;
  /** A locale, for a test. The default is the reader's own. */
  locale?: string;
}

/**
 * The day names for one rollover hour. With no hour, or with text that
 * is not a label, a name is the UTC date of the label, as before.
 */
export function makeDayNames(
  closesAtUtc: string | null,
  options: DayNameOptions = {},
): DayNames {
  const zone =
    options.timeZone === undefined ? {} : { timeZone: options.timeZone };
  const long = new Intl.DateTimeFormat(options.locale, {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...zone,
  });
  const short = new Intl.DateTimeFormat(options.locale, {
    month: "short",
    day: "numeric",
    ...zone,
  });
  const letter = new Intl.DateTimeFormat(options.locale, {
    weekday: "narrow",
    ...zone,
  });
  const utcLetter = new Intl.DateTimeFormat(options.locale, {
    weekday: "narrow",
    timeZone: "UTC",
  });
  const numbers = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    ...zone,
  });
  const utcNumbers = new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    timeZone: "UTC",
  });
  return {
    calendarDate(label) {
      const start = dayStart(label, closesAtUtc);
      const midnight = labelMidnight(label);
      if (start === null && midnight === null) {
        return null;
      }
      // With no rollover hour, the date is the UTC date of the label.
      const parts = (start === null ? utcNumbers : numbers).formatToParts(
        start ?? new Date(midnight as number),
      );
      const read = (type: string): number =>
        Number(parts.find((part) => part.type === type)?.value);
      return {
        year: read("year"),
        month: read("month") - 1,
        date: read("day"),
      };
    },
    long(label) {
      const start = dayStart(label, closesAtUtc);
      return start === null ? formatDay(label) : long.format(start);
    },
    short(label) {
      const start = dayStart(label, closesAtUtc);
      return start === null ? formatShortDay(label) : short.format(start);
    },
    weekdayLetter(label) {
      const start = dayStart(label, closesAtUtc);
      if (start !== null) {
        return letter.format(start);
      }
      const midnight = labelMidnight(label);
      return midnight === null ? "" : utcLetter.format(new Date(midnight));
    },
  };
}

/**
 * The day names of this server. The rollover hour comes from the
 * season facts, which the top bar reads on each screen, so this adds no
 * request. Until the answer is in, a name is the UTC date of the label.
 */
export function useDayNames(): DayNames {
  const api = useApi();
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const hour = about.data?.closes_at_utc ?? null;
  return useMemo(() => makeDayNames(hour), [hour]);
}
