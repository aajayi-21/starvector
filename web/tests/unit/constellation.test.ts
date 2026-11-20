import { describe, expect, it } from "vitest";

import { CONSTELLATION_DAYS, starsOf } from "../../src/ui/constellation";

const BOX = { left: 0, right: 600, top: 0, bottom: 200, small: 2, large: 6 };

/** A history as the server sends it: the latest day first. */
function history(results: ReadonlyArray<number>) {
  return results.map((p, index) => ({
    day: `2026-08-${String(20 - index).padStart(2, "0")}`,
    p,
  }));
}

describe("the stars of the home screen", () => {
  it("draws the latest results, oldest first, across the row", () => {
    const stars = starsOf(history([0.5, 0.9, 0.1]), BOX);
    expect(stars.map((star) => star.day)).toEqual([
      "2026-08-18",
      "2026-08-19",
      "2026-08-20",
    ]);
    expect(stars.map((star) => star.x)).toEqual([0, 300, 600]);
  });

  it("puts a better result higher and draws it larger", () => {
    const [low, high] = starsOf(history([1, 0]), BOX);
    expect(low?.y).toBe(200);
    expect(high?.y).toBe(0);
    expect(low?.r).toBe(2);
    expect(high?.r).toBe(6);
  });

  it("puts a result of chance on the middle line", () => {
    const [only] = starsOf(history([0.5]), BOX);
    expect(only?.y).toBe(100);
    // One star stands in the middle of the row.
    expect(only?.x).toBe(300);
  });

  it("marks one best result, and keeps each label off the middle line", () => {
    const stars = starsOf(history([0.2, 0.8, 0.8, 0.6]), BOX);
    expect(stars.filter((star) => star.best)).toHaveLength(1);
    for (const star of stars) {
      expect(star.labelAbove).toBe(star.p >= 0.5);
    }
  });

  it("shows no more than the latest days of the row", () => {
    const stars = starsOf(history(Array.from({ length: 12 }, () => 0.5)), BOX);
    expect(stars).toHaveLength(CONSTELLATION_DAYS);
    expect(stars.at(-1)?.day).toBe("2026-08-20");
  });

  it("draws nothing for a player with no result", () => {
    expect(starsOf([], BOX)).toEqual([]);
  });
});
