/**
 * The grid of one month, for the calendar of the Play place
 * (ui/day-stepper.tsx). Pure functions over year, month, and date, with
 * no clock and no zone: the caller says which dates hold a day.
 */

import type { CalendarDate } from "./day-names";

/** A month of a year: the month counts from 0, as in `Date`. */
export interface Month {
  year: number;
  month: number;
}

/** One key for a date, to look a day up by. */
export function dateKey(date: CalendarDate): string {
  return `${date.year}-${date.month}-${date.date}`;
}

/** The month that a date is in. */
export function monthOf(date: CalendarDate): Month {
  return { year: date.year, month: date.month };
}

/** The month `by` months after this one; a negative count goes back. */
export function shiftMonth(month: Month, by: number): Month {
  const index = month.year * 12 + month.month + by;
  return { year: Math.floor(index / 12), month: ((index % 12) + 12) % 12 };
}

/** Less than 0 when `a` is the earlier month, 0 for the same month. */
export function compareMonths(a: Month, b: Month): number {
  return a.year * 12 + a.month - (b.year * 12 + b.month);
}

/**
 * The cells of a month, a week to a row, Sunday first: null for each
 * empty cell before the first date, then the dates in order.
 */
export function monthCells(month: Month): Array<CalendarDate | null> {
  const lead = new Date(Date.UTC(month.year, month.month, 1)).getUTCDay();
  const days = new Date(Date.UTC(month.year, month.month + 1, 0)).getUTCDate();
  return [
    ...Array.from({ length: lead }, () => null),
    ...Array.from({ length: days }, (_, index) => ({
      year: month.year,
      month: month.month,
      date: index + 1,
    })),
  ];
}
