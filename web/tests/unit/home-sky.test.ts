import { describe, expect, it } from "vitest";

import { randomOf } from "../../src/sky/core";
import {
  crownDays,
  crownPlace,
  crownPlaces,
  crownStarRadius,
  ghostSpot,
  quietField,
  shiftDay,
} from "../../src/sky/home";

describe("the days of the crown", () => {
  const results = new Map([
    ["2026-11-19", 0.51],
    ["2026-11-18", 0.62],
    ["2026-11-16", 0.81],
  ]);

  it("counts the streak back from the newest revealed day, oldest first", () => {
    expect(crownDays(3, "2026-11-19", results, 13)).toEqual([
      { day: "2026-11-17", p: null },
      { day: "2026-11-18", p: 0.62 },
      { day: "2026-11-19", p: 0.51 },
    ]);
  });

  it("draws the latest days of a streak longer than the crown", () => {
    const days = crownDays(47, "2026-11-19", results, 13);
    expect(days).toHaveLength(13);
    expect(days[0]?.day).toBe("2026-11-07");
    expect(days[12]?.day).toBe("2026-11-19");
  });

  it("has no day with no streak or no revealed day", () => {
    expect(crownDays(0, "2026-11-19", results, 13)).toEqual([]);
    expect(crownDays(4, undefined, results, 13)).toEqual([]);
  });

  it("moves a day across a month", () => {
    expect(shiftDay("2026-11-01", -1)).toBe("2026-10-31");
    expect(shiftDay("2026-12-31", 1)).toBe("2027-01-01");
  });
});

describe("the arc of the crown", () => {
  it("is highest in the middle and lowest at its two ends", () => {
    expect(crownPlace(0.5).y).toBe(0);
    expect(crownPlace(0).y).toBe(1);
    expect(crownPlace(1).y).toBe(1);
    expect(crownPlace(0.5).x).toBeCloseTo(0.5);
  });

  it("puts one thing at the top of the arc", () => {
    expect(crownPlaces(1)).toEqual([crownPlace(0.5)]);
  });

  it("spreads the days from left to right, inside the crown", () => {
    const places = crownPlaces(7);
    expect(places).toHaveLength(7);
    for (let index = 1; index < places.length; index += 1) {
      const before = places[index - 1];
      const place = places[index];
      expect(place?.x).toBeGreaterThan(before?.x ?? 1);
    }
    expect(places[0]?.x).toBeGreaterThan(0);
    expect(places[6]?.x).toBeLessThan(1);
    // The arc is the same on its two sides.
    expect(places[0]?.y).toBeCloseTo(places[6]?.y ?? -1);
  });

  it("draws a larger star for a better result", () => {
    expect(crownStarRadius(0.9)).toBeGreaterThan(crownStarRadius(0.2));
    expect(crownStarRadius(null)).toBeGreaterThan(0);
  });
});

describe("the quiet sky", () => {
  it("is the same for the same seed", () => {
    expect(quietField(1440, 840, randomOf(7))).toEqual(
      quietField(1440, 840, randomOf(7)),
    );
  });

  it("keeps each star inside the screen, with a few bright ones", () => {
    const stars = quietField(1440, 840, randomOf(7));
    for (const star of stars) {
      expect(star.x).toBeGreaterThanOrEqual(0);
      expect(star.x).toBeLessThanOrEqual(1);
      expect(star.y).toBeGreaterThanOrEqual(0);
      expect(star.y).toBeLessThanOrEqual(1);
    }
    const bright = stars.filter((star) => star.bright).length;
    expect(bright).toBeGreaterThanOrEqual(3);
    expect(bright).toBeLessThanOrEqual(6);
  });

  it("has fewer stars on a small screen", () => {
    expect(quietField(390, 700, randomOf(7)).length).toBeLessThan(
      quietField(1440, 840, randomOf(7)).length,
    );
  });
});

describe("the place of a faint sketch", () => {
  it("is larger for a better result", () => {
    const high = ghostSpot(0.95, randomOf(3), null);
    const low = ghostSpot(0.2, randomOf(3), null);
    expect(high.share).toBeGreaterThan(low.share);
  });

  it("stands inside the screen and tilts a little", () => {
    const random = randomOf(11);
    for (let index = 0; index < 50; index += 1) {
      const spot = ghostSpot(0.5, random, null);
      expect(spot.x).toBeGreaterThan(0.1);
      expect(spot.x).toBeLessThan(0.9);
      expect(spot.y).toBeGreaterThan(0.15);
      expect(spot.y).toBeLessThan(0.85);
      expect(Math.abs(spot.tilt)).toBeLessThanOrEqual(7);
    }
  });

  it("keeps away from the other sketch on the screen", () => {
    const other = { x: 0.2, y: 0.3 };
    const random = randomOf(5);
    let total = 0;
    for (let index = 0; index < 40; index += 1) {
      const spot = ghostSpot(0.5, random, other);
      total += Math.hypot(spot.x - other.x, spot.y - other.y);
    }
    // The farthest of twelve places is well clear on average.
    expect(total / 40).toBeGreaterThan(0.45);
  });
});
