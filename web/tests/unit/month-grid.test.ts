import { describe, expect, it } from "vitest";

import { makeDayNames } from "../../src/ui/day-names";
import {
  compareMonths,
  dateKey,
  monthCells,
  monthOf,
  shiftMonth,
} from "../../src/ui/month-grid";

describe("the grid of a month", () => {
  it("starts November 2026 on a Sunday, with 30 dates", () => {
    const cells = monthCells({ year: 2026, month: 10 });
    expect(cells).toHaveLength(30);
    expect(cells[0]).toEqual({ year: 2026, month: 10, date: 1 });
    expect(cells[29]).toEqual({ year: 2026, month: 10, date: 30 });
  });

  it("leaves the cells before the first date empty", () => {
    // October 1, 2026 is a Thursday: four empty cells, then 31 dates.
    const cells = monthCells({ year: 2026, month: 9 });
    expect(cells.slice(0, 4)).toEqual([null, null, null, null]);
    expect(cells[4]).toEqual({ year: 2026, month: 9, date: 1 });
    expect(cells).toHaveLength(35);
  });

  it("knows February of a leap year", () => {
    expect(
      monthCells({ year: 2028, month: 1 }).filter((cell) => cell !== null),
    ).toHaveLength(29);
  });

  it("steps over the end of a year", () => {
    expect(shiftMonth({ year: 2026, month: 11 }, 1)).toEqual({
      year: 2027,
      month: 0,
    });
    expect(shiftMonth({ year: 2026, month: 0 }, -1)).toEqual({
      year: 2025,
      month: 11,
    });
  });

  it("orders the months", () => {
    expect(
      compareMonths({ year: 2026, month: 9 }, { year: 2026, month: 10 }),
    ).toBeLessThan(0);
    expect(
      compareMonths({ year: 2027, month: 0 }, { year: 2026, month: 11 }),
    ).toBeGreaterThan(0);
    expect(
      compareMonths({ year: 2026, month: 10 }, { year: 2026, month: 10 }),
    ).toBe(0);
  });

  it("gives one key to one date", () => {
    const date = { year: 2026, month: 10, date: 19 };
    expect(dateKey(date)).toBe(dateKey({ ...date }));
    expect(dateKey(date)).not.toBe(dateKey({ ...date, date: 20 }));
    expect(monthOf(date)).toEqual({ year: 2026, month: 10 });
  });
});

describe("the calendar date of a day", () => {
  it("is the local date on which the day started", () => {
    // A day that ends at 00:00 UTC started the evening before in New York.
    const names = makeDayNames("00:00", { timeZone: "America/New_York" });
    expect(names.calendarDate("2026-11-21")).toEqual({
      year: 2026,
      month: 10,
      date: 20,
    });
    // The same day in Tokyo started on the morning of its label.
    const tokyo = makeDayNames("00:00", { timeZone: "Asia/Tokyo" });
    expect(tokyo.calendarDate("2026-11-21")).toEqual({
      year: 2026,
      month: 10,
      date: 21,
    });
  });

  it("is the date of the label with no rollover hour", () => {
    expect(makeDayNames(null).calendarDate("2026-11-21")).toEqual({
      year: 2026,
      month: 10,
      date: 21,
    });
  });

  it("is null for text that is not a label", () => {
    expect(makeDayNames("00:00").calendarDate("soon")).toBeNull();
  });
});
