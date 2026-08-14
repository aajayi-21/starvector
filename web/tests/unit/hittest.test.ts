import { describe, expect, it } from "vitest";

import {
  addStroke,
  EMPTY_DOC,
  hitTest,
  SELECT_TOLERANCE_TOUCH_PX,
  selectTolerance,
} from "../../src/sketch/core";

const BASELINE: [number, number][] = [
  [0, 0],
  [1, 0],
];

describe("hit-testing", () => {
  const doc = addStroke(EMPTY_DOC, BASELINE, 0, 1);

  it("uses the spec tolerances", () => {
    expect(selectTolerance(3)).toBe(8);
    expect(SELECT_TOLERANCE_TOUCH_PX).toBe(12);
  });

  it("measures perpendicular distance to the segment", () => {
    expect(hitTest(doc, [50, 7.9], 100, 100, 8)).toBe(1);
    expect(hitTest(doc, [50, 8.1], 100, 100, 8)).toBeNull();
  });

  it("clamps to the segment ends", () => {
    // 10 px past the end: distance is 10, not the perpendicular 0.
    expect(hitTest(doc, [110, 0], 100, 100, 8)).toBeNull();
    expect(hitTest(doc, [110, 0], 100, 100, SELECT_TOLERANCE_TOUCH_PX)).toBe(1);
  });

  it("lets the newest stroke win a tie", () => {
    const two = addStroke(doc, BASELINE, 1, 2);
    expect(hitTest(two, [50, 0], 100, 100, 8)).toBe(2);
  });

  it("handles a single-point stroke as a point distance", () => {
    const dot = addStroke(EMPTY_DOC, [[0.5, 0.5]], 0, 7);
    expect(hitTest(dot, [50, 55], 100, 100, 8)).toBe(7);
    expect(hitTest(dot, [50, 65], 100, 100, 8)).toBeNull();
  });
});
