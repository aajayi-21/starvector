import { describe, expect, it } from "vitest";

import { dayClose, dayStart, labelAt } from "../../src/ui/day-calendar";
import { makeDayNames } from "../../src/ui/day-names";
import { formatCloseAt, formatCloseClock } from "../../src/ui/format";

const iso = (date: Date | null): string | null =>
  date === null ? null : date.toISOString();

describe("the day calendar, as service/schedule.py has it", () => {
  // The cases of tests/service/test_day_calendar.py: the close instant
  // of a label. The start is 24 hours before it.
  it.each([
    ["22:00", "2026-09-24", "2026-09-24T22:00:00.000Z"],
    ["00:00", "2026-09-24", "2026-09-25T00:00:00.000Z"],
    ["06:30", "2026-09-24", "2026-09-25T06:30:00.000Z"],
    ["12:00", "2026-12-31", "2026-12-31T12:00:00.000Z"],
    ["00:00", "2026-12-31", "2027-01-01T00:00:00.000Z"],
  ])("with the hour %s, the day %s closes at %s", (hour, label, closes) => {
    expect(iso(dayClose(label, hour))).toBe(closes);
    const start = dayStart(label, hour) as Date;
    expect(Date.parse(closes) - start.getTime()).toBe(86_400_000);
  });

  it("starts a day on its label before noon, and the day before from noon", () => {
    expect(iso(dayStart("2026-11-21", "00:00"))).toBe(
      "2026-11-21T00:00:00.000Z",
    );
    expect(iso(dayStart("2026-11-21", "11:59"))).toBe(
      "2026-11-21T11:59:00.000Z",
    );
    expect(iso(dayStart("2026-11-21", "12:00"))).toBe(
      "2026-11-20T12:00:00.000Z",
    );
    expect(iso(dayStart("2026-11-21", "22:00"))).toBe(
      "2026-11-20T22:00:00.000Z",
    );
    // The first day of a year, with a late hour, starts in the year before.
    expect(iso(dayStart("2027-01-01", "22:00"))).toBe(
      "2026-12-31T22:00:00.000Z",
    );
  });

  it("gives no start with no hour, a bad hour, or a bad label", () => {
    expect(dayStart("2026-11-21", null)).toBeNull();
    expect(dayStart("2026-11-21", "24:00")).toBeNull();
    expect(dayStart("2026-11-21", "6:00")).toBeNull();
    expect(dayStart("2026-02-31", "00:00")).toBeNull();
    expect(dayStart("yesterday", "00:00")).toBeNull();
  });

  // The cases of test_the_label_is_the_date_with_most_of_the_window.
  it.each([
    ["22:00", "2026-09-24T21:59:59Z", "2026-09-24"],
    ["22:00", "2026-09-24T22:00:00Z", "2026-09-25"],
    ["00:00", "2026-09-24T00:00:00Z", "2026-09-24"],
    ["00:00", "2026-09-24T23:59:59Z", "2026-09-24"],
    ["06:00", "2026-09-24T05:59:59Z", "2026-09-23"],
    ["06:00", "2026-09-24T06:00:00Z", "2026-09-24"],
    ["12:00", "2026-09-24T11:59:59Z", "2026-09-24"],
    ["12:00", "2026-09-24T12:00:00Z", "2026-09-25"],
    [null, "2026-09-24T23:30:00Z", "2026-09-24"],
  ])("with the hour %s, the instant %s is in the day %s", (hour, at, label) => {
    expect(labelAt(new Date(at), hour)).toBe(label);
  });

  it("holds a label from its start to its close", () => {
    for (const hour of ["00:00", "06:30", "12:00", "22:00"]) {
      const start = dayStart("2026-11-21", hour) as Date;
      const close = dayClose("2026-11-21", hour) as Date;
      expect(labelAt(start, hour)).toBe("2026-11-21");
      expect(labelAt(new Date(close.getTime() - 1000), hour)).toBe(
        "2026-11-21",
      );
      expect(labelAt(close, hour)).toBe("2026-11-22");
    }
  });
});

describe("the name of a day in the reader's zone", () => {
  const LOCALE = "en-US";

  it("names a day for the local date on which it started", () => {
    // Production closes at 00:00 UTC. In Los Angeles the day labeled
    // Nov 21 runs from 4 PM Friday to 4 PM Saturday.
    const pacific = makeDayNames("00:00", {
      timeZone: "America/Los_Angeles",
      locale: LOCALE,
    });
    expect(pacific.long("2026-11-21")).toBe("Fri, Nov 20");
    expect(pacific.short("2026-11-21")).toBe("Nov 20");
    expect(pacific.weekdayLetter("2026-11-21")).toBe("F");
  });

  it("keeps the label's date where the day starts on it", () => {
    const utc = makeDayNames("00:00", { timeZone: "UTC", locale: LOCALE });
    expect(utc.long("2026-11-21")).toBe("Sat, Nov 21");
    const tokyo = makeDayNames("00:00", {
      timeZone: "Asia/Tokyo",
      locale: LOCALE,
    });
    expect(tokyo.long("2026-11-21")).toBe("Sat, Nov 21");
    expect(tokyo.weekdayLetter("2026-11-21")).toBe("S");
  });

  it("gives consecutive days consecutive names", () => {
    const pacific = makeDayNames("00:00", {
      timeZone: "America/Los_Angeles",
      locale: LOCALE,
    });
    expect(
      ["2026-11-29", "2026-11-30", "2026-12-01", "2026-12-02"].map((label) =>
        pacific.short(label),
      ),
    ).toEqual(["Nov 28", "Nov 29", "Nov 30", "Dec 1"]);
  });

  it("falls to the UTC date of the label with no hour", () => {
    const names = makeDayNames(null, {
      timeZone: "America/Los_Angeles",
      locale: LOCALE,
    });
    // formatDay reads the label in UTC, in the reader's own locale.
    expect(names.long("2026-11-21")).toMatch(/21/);
    expect(names.short("2026-11-21")).toMatch(/21/);
    expect(names.weekdayLetter("2026-11-21")).toBe("S");
  });

  it("returns text that is not a label as it is", () => {
    const names = makeDayNames("00:00", { timeZone: "UTC", locale: LOCALE });
    expect(names.long("soon")).toBe("soon");
    expect(names.short("soon")).toBe("soon");
    expect(names.weekdayLetter("soon")).toBe("");
  });
});

describe("the close of the day in play, against the reader's clock", () => {
  // Local wall-clock instants, so the test holds in each zone.
  const at = (day: number, hour: number): Date =>
    new Date(2026, 10, day, hour, 0, 0);

  it("gives the clock alone when the close is today", () => {
    const text = formatCloseClock(
      at(20, 16).toISOString(),
      at(20, 9).getTime(),
    );
    expect(text).toMatch(/^\d{1,2}:\d{2}/);
    expect(text).not.toMatch(/tomorrow/);
    expect(
      formatCloseAt(at(20, 16).toISOString(), at(20, 9).getTime()),
    ).toMatch(/^at \d{1,2}:\d{2}/);
  });

  it("says tomorrow when the close is on the next local date", () => {
    const now = at(20, 17).getTime();
    expect(formatCloseClock(at(21, 16).toISOString(), now)).toMatch(
      /^tomorrow \d{1,2}:\d{2}/,
    );
    expect(formatCloseAt(at(21, 16).toISOString(), now)).toMatch(
      /^tomorrow at \d{1,2}:\d{2}/,
    );
  });

  it("names the weekday when the close is further away", () => {
    const now = at(20, 17).getTime();
    const text = formatCloseClock(at(23, 16).toISOString(), now);
    expect(text).not.toMatch(/tomorrow/);
    expect(text).toMatch(/\d{1,2}:\d{2}/);
    expect(text.length).toBeGreaterThan(
      formatCloseClock(at(20, 18).toISOString(), now).length,
    );
  });

  it("returns text that is not an instant as it is", () => {
    expect(formatCloseClock("soon", 0)).toBe("soon");
  });
});
