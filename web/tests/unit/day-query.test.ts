import { describe, expect, it } from "vitest";

import {
  dayPollMs,
  NEAR_CLOSE_MS,
  POLL_FAR_MS,
  POLL_NEAR_MS,
  POLL_REVEALED_MS,
} from "../../src/api/day-query";
import type { DayStatus, DayView } from "../../src/api/types";

const NOW = Date.parse("2026-08-14T12:00:00Z");

function view(status: DayStatus, closesAt: string | null): DayView {
  return {
    day: "2026-08-14",
    trial_code: "ABC123",
    status,
    commitment: "c",
    player: "ade",
    submitted: false,
    sends: 0,
    relation_vocabulary: [],
    canvas_px: 512,
    min_strokes: 2,
    closes_at: closesAt,
  };
}

const at = (offsetMs: number): string => new Date(NOW + offsetMs).toISOString();

describe("the day poll", () => {
  it("polls near when no day is known", () => {
    expect(dayPollMs(undefined, NOW)).toBe(POLL_NEAR_MS);
  });

  it("polls near during a close", () => {
    expect(dayPollMs(view("closing", null), NOW)).toBe(POLL_NEAR_MS);
    expect(dayPollMs(view("closed", null), NOW)).toBe(POLL_NEAR_MS);
  });

  it("polls far on an open day well before the close", () => {
    const closes = at(NEAR_CLOSE_MS + 1);
    expect(dayPollMs(view("open", closes), NOW)).toBe(POLL_FAR_MS);
  });

  it("polls near around the close time", () => {
    expect(dayPollMs(view("open", at(NEAR_CLOSE_MS)), NOW)).toBe(POLL_NEAR_MS);
    expect(dayPollMs(view("open", at(1000)), NOW)).toBe(POLL_NEAR_MS);
  });

  it("polls near after a close time that has passed", () => {
    expect(dayPollMs(view("open", at(-3_600_000)), NOW)).toBe(POLL_NEAR_MS);
  });

  it("polls far with no close time", () => {
    expect(dayPollMs(view("open", null), NOW)).toBe(POLL_FAR_MS);
  });

  it("polls gently on a revealed day, waiting for the next open", () => {
    expect(dayPollMs(view("revealed", null), NOW)).toBe(POLL_REVEALED_MS);
  });
});
