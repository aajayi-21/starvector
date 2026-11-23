import { describe, expect, it } from "vitest";

import {
  chartPlace,
  chartStarRadius,
  FOOTPRINT,
  figureOf,
  randomOf,
  type SkyBounds,
  scatter,
  seedOf,
  simplify,
  sizeShare,
} from "../../src/sky/core";

const BOUNDS: SkyBounds = {
  left: 40,
  top: 14,
  right: 1400,
  bottom: 786,
  // The title's corner and the hint at the foot.
  keepOut: [
    { left: 0, top: 0, right: 680, bottom: 176 },
    { left: 510, top: 716, right: 930, bottom: 800 },
  ],
};

/** 34 results with a spread around 50%, as a player's history holds. */
const RESULTS = [
  41, 58, 12, 67, 49, 83, 36, 54, 71, 27, 62, 45, 9, 77, 52, 38, 66, 31, 59, 88,
  44, 23, 69, 96, 55, 40, 74, 18, 63, 47, 81, 35, 62, 51,
].map((percent) => percent / 100);

describe("the size of a drawing", () => {
  it("grows with the result", () => {
    for (let percent = 1; percent <= 100; percent += 1) {
      expect(sizeShare(percent / 100)).toBeGreaterThan(
        sizeShare((percent - 1) / 100),
      );
    }
    expect(sizeShare(1)).toBeCloseTo(1);
  });

  it("is steep: 96% draws three times as wide as 50%", () => {
    const ratio = sizeShare(0.96) / sizeShare(0.5);
    expect(ratio).toBeGreaterThan(2.8);
    expect(ratio).toBeLessThan(3.1);
    // The poorest result keeps a size: it is small, and it is there.
    expect(sizeShare(0)).toBeGreaterThan(0.1);
  });

  it("takes a result outside 0 to 1 as the nearest end", () => {
    expect(sizeShare(-1)).toBe(sizeShare(0));
    expect(sizeShare(7)).toBe(sizeShare(1));
  });
});

describe("the seed of a sky", () => {
  it("is the same for the same text, and differs between texts", () => {
    expect(seedOf("oddcompass")).toBe(seedOf("oddcompass"));
    expect(seedOf("oddcompass")).not.toBe(seedOf("tidewatcher"));
  });

  it("gives the same sequence each time", () => {
    const first = randomOf(7);
    const second = randomOf(7);
    for (let draw = 0; draw < 20; draw += 1) {
      const value = first();
      expect(value).toBe(second());
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
  });
});

describe("the scatter of the drawings", () => {
  const sky = scatter(RESULTS, BOUNDS, seedOf("oddcompass"));

  it("gives the same sky for the same player, and a new one for the next", () => {
    const again = scatter(RESULTS, BOUNDS, seedOf("oddcompass"));
    expect([...again.x]).toEqual([...sky.x]);
    expect([...again.y]).toEqual([...sky.y]);
    const other = scatter(RESULTS, BOUNDS, seedOf("tidewatcher"));
    expect([...other.x]).not.toEqual([...sky.x]);
  });

  it("sizes each drawing by its result alone", () => {
    for (let index = 0; index < RESULTS.length; index += 1) {
      const share = sizeShare(RESULTS[index] as number) / sizeShare(0.96);
      expect((sky.size[index] as number) / sky.largest).toBeCloseTo(share, 4);
    }
    // The largest is a drawing a player can read, not a speck.
    expect(sky.largest).toBeGreaterThan(120);
  });

  it("puts no two drawings on each other", () => {
    for (let a = 0; a < RESULTS.length; a += 1) {
      for (let b = a + 1; b < RESULTS.length; b += 1) {
        const apart = Math.hypot(
          (sky.x[a] as number) - (sky.x[b] as number),
          (sky.y[a] as number) - (sky.y[b] as number),
        );
        const reach =
          ((sky.size[a] as number) + (sky.size[b] as number)) * FOOTPRINT;
        expect(apart).toBeGreaterThanOrEqual(reach);
      }
    }
  });

  it("keeps each drawing in the sky and off the title and the hint", () => {
    for (let index = 0; index < RESULTS.length; index += 1) {
      const x = sky.x[index] as number;
      const y = sky.y[index] as number;
      const reach = (sky.size[index] as number) * FOOTPRINT;
      expect(x - reach).toBeGreaterThanOrEqual(BOUNDS.left);
      expect(x + reach).toBeLessThanOrEqual(BOUNDS.right);
      expect(y - reach).toBeGreaterThanOrEqual(BOUNDS.top);
      expect(y + reach).toBeLessThanOrEqual(BOUNDS.bottom);
      for (const rect of BOUNDS.keepOut) {
        const inside =
          x + reach > rect.left &&
          x - reach < rect.right &&
          y + reach > rect.top &&
          y - reach < rect.bottom;
        expect(inside).toBe(false);
      }
    }
  });

  it("stands on no grid: the middles share no row and no column", () => {
    const columns = new Set([...sky.x].map((x) => Math.round(x)));
    const rows = new Set([...sky.y].map((y) => Math.round(y)));
    expect(columns.size).toBeGreaterThan(RESULTS.length * 0.8);
    expect(rows.size).toBeGreaterThan(RESULTS.length * 0.8);
  });

  it("holds one day, no day, and a long history", () => {
    const one = scatter([0.5], BOUNDS, 1);
    expect(one.size).toHaveLength(1);
    expect(one.largest).toBeGreaterThan(0);
    expect(scatter([], BOUNDS, 1).size).toHaveLength(0);
    const many = scatter(
      Array.from({ length: 300 }, (_, index) => ((index * 37) % 97) / 100),
      BOUNDS,
      1,
    );
    expect(many.size).toHaveLength(300);
    expect(many.largest).toBeGreaterThan(20);
  });

  it("stays whole in a sky with no room", () => {
    const none = scatter(
      RESULTS,
      { left: 0, top: 0, right: 4, bottom: 4, keepOut: [] },
      1,
    );
    expect(none.x).toHaveLength(RESULTS.length);
    expect([...none.x].every((x) => Number.isFinite(x))).toBe(true);
  });
});

describe("the chart of the days", () => {
  const box = { left: 100, top: 50, right: 900, bottom: 450 };

  it("runs from the first day on the left to the newest on the right", () => {
    expect(chartPlace(0, 5, 0.5, box).x).toBe(100);
    expect(chartPlace(4, 5, 0.5, box).x).toBe(900);
    expect(chartPlace(2, 5, 0.5, box).x).toBe(500);
  });

  it("puts 100% at the top, 0% at the foot, and 50% in the middle", () => {
    expect(chartPlace(0, 5, 1, box).y).toBe(50);
    expect(chartPlace(0, 5, 0, box).y).toBe(450);
    expect(chartPlace(0, 5, 0.5, box).y).toBe(250);
  });

  it("stands one day in the middle", () => {
    expect(chartPlace(0, 1, 0.5, box).x).toBe(500);
  });

  it("draws a better result as a larger star", () => {
    expect(chartStarRadius(0.9, false)).toBeGreaterThan(
      chartStarRadius(0.1, false),
    );
    expect(chartStarRadius(0.9, true)).toBeLessThan(
      chartStarRadius(0.9, false),
    );
  });
});

describe("a sketch as a constellation", () => {
  it("thins a straight line to its two ends, and keeps a corner", () => {
    const straight = Array.from(
      { length: 9 },
      (_, index) => [index / 8, 0.5] as const,
    );
    expect(simplify(straight, 0.01)).toEqual([
      [0, 0.5],
      [1, 0.5],
    ]);
    const corner = [
      [0, 0],
      [0.5, 0.01],
      [1, 0],
      [1, 0.5],
      [1, 1],
    ] as const;
    expect(simplify(corner, 0.05)).toEqual([
      [0, 0],
      [1, 0],
      [1, 1],
    ]);
  });

  it("has no figure for a send with no sketch", () => {
    expect(figureOf([])).toBeNull();
    expect(figureOf([{ points: [] }])).toBeNull();
  });

  it("fits a small sketch in a corner to the whole square", () => {
    const figure = figureOf([
      {
        points: [
          [0.8, 0.8],
          [0.9, 0.8],
          [0.9, 0.95],
        ],
      },
      {
        points: [
          [0.8, 0.95],
          [0.9, 0.95],
        ],
        color: "#81a1c1",
      },
    ]);
    if (figure === null) {
      throw new Error("the sketch has points");
    }
    const all = figure.lines.flatMap((line) => line.points);
    for (const [x, y] of all) {
      expect(x).toBeGreaterThanOrEqual(0);
      expect(x).toBeLessThanOrEqual(1);
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThanOrEqual(1);
    }
    const ys = all.map(([, y]) => y);
    // The taller side of the sketch takes the square, less the margin.
    expect(Math.max(...ys) - Math.min(...ys)).toBeCloseTo(0.88);
    expect(figure.lines[1]?.color).toBe("#81a1c1");
    expect(figure.lines[0]?.color).toBeUndefined();
  });

  it("stands the day's star on the first point drawn", () => {
    const figure = figureOf([
      {
        points: [
          [0.2, 0.3],
          [0.6, 0.3],
          [0.6, 0.7],
        ],
      },
    ]);
    expect(figure?.anchor).toEqual(figure?.lines[0]?.points[0]);
    // The ends and the corner are the stars of the figure.
    expect(figure?.dots).toHaveLength(3);
  });

  it("does not blow a dot up to the size of the square", () => {
    const figure = figureOf([
      {
        points: [
          [0.5, 0.5],
          [0.51, 0.5],
        ],
      },
    ]);
    const xs = figure?.lines[0]?.points.map(([x]) => x) ?? [];
    expect(Math.max(...xs) - Math.min(...xs)).toBeLessThan(0.1);
  });
});
