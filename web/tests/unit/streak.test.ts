import { describe, expect, it } from "vitest";

import { streakLabel, streakTier } from "../../src/ui/streak";

describe("the streak tiers (spec H1 §4, D1)", () => {
  it.each([
    [0, 0],
    [1, 0],
    [2, 0],
    [3, 1],
    [6, 1],
    [7, 2],
    [29, 2],
    [30, 3],
    [365, 3],
  ])("a streak of %i days is tier %i", (streak, tier) => {
    expect(streakTier(streak)).toBe(tier);
  });

  it("words the label for a screen reader", () => {
    expect(streakLabel(12)).toBe("12-day streak");
  });
});
