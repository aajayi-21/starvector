import { describe, expect, it } from "vitest";

import type { Point, SketchDoc } from "../../src/sketch/core";
import {
  addStroke,
  EMPTY_DOC,
  ERASER_RADIUS_PX,
  ERASER_RADIUS_TOUCH_PX,
  eraseAlong,
  eraserRadius,
  makeGroup,
  serialize,
} from "../../src/sketch/core";

// A 100 by 100 CSS pixel canvas: a normalized 0.4 is 40 pixels.
const W = 100;
const H = 100;
const px = (x: number, y: number): Point => [x / W, y / H];

/** One horizontal line at y = 50, from x = 10 to x = 90, with id 1. */
function oneLine(): SketchDoc {
  return addStroke(EMPTY_DOC, [px(10, 50), px(90, 50)], 0, 1);
}

function xs(doc: SketchDoc): number[][] {
  return doc.strokes.map((stroke) =>
    stroke.points.map(([x]) => Math.round(x * W * 1e6) / 1e6),
  );
}

describe("the eraser cuts a stroke where it passes", () => {
  it("cuts at the eraser's edge, not at the stroke's points", () => {
    // A tap at the middle, radius 10: the line loses x = 40 to x = 60.
    const { doc, nextId } = eraseAlong(oneLine(), [[50, 50]], 10, W, H, 7);
    expect(xs(doc)).toEqual([
      [10, 40],
      [60, 90],
    ]);
    expect(doc.strokes.map((stroke) => stroke.id)).toEqual([7, 8]);
    expect(nextId).toBe(9);
  });

  it("cuts a shorter run when the eraser is off the line", () => {
    // 6 pixels off the line, radius 10: the chord is 16 pixels wide.
    const { doc } = eraseAlong(oneLine(), [[50, 56]], 10, W, H, 2);
    expect(xs(doc)).toEqual([
      [10, 42],
      [58, 90],
    ]);
  });

  it("erases what lies between two samples of a quick move", () => {
    // The eraser crosses the line between two samples that are both
    // far from it: the swept path cuts, and the two discs alone do not.
    const vertical = addStroke(EMPTY_DOC, [px(50, 10), px(50, 90)], 0, 1);
    const { doc } = eraseAlong(
      vertical,
      [
        [20, 50],
        [80, 50],
      ],
      5,
      W,
      H,
      2,
    );
    expect(
      doc.strokes.map((stroke) =>
        stroke.points.map(([, y]) => Math.round(y * H * 1e6) / 1e6),
      ),
    ).toEqual([
      [10, 45],
      [55, 90],
    ]);
  });

  it("removes a point of the stroke that is under the eraser", () => {
    // A corner at (50, 50), fully inside the eraser.
    const corner = addStroke(
      EMPTY_DOC,
      [px(10, 50), px(50, 50), px(50, 90)],
      0,
      1,
    );
    const { doc } = eraseAlong(corner, [[50, 50]], 10, W, H, 2);
    expect(doc.strokes).toHaveLength(2);
    expect(doc.strokes[0]?.points).toEqual([px(10, 50), px(40, 50)]);
    expect(doc.strokes[1]?.points[0]?.[1]).toBeCloseTo(0.6, 9);
    expect(doc.strokes[1]?.points[1]).toEqual(px(50, 90));
  });

  it("keeps the point objects that the eraser does not touch", () => {
    const before = addStroke(
      EMPTY_DOC,
      [px(10, 50), px(30, 50), px(70, 50), px(90, 50)],
      0,
      1,
    );
    const { doc } = eraseAlong(before, [[50, 50]], 5, W, H, 2);
    const source = before.strokes[0]?.points ?? [];
    // No drift: the kept points are the same objects, by identity.
    expect(doc.strokes[0]?.points[0]).toBe(source[0]);
    expect(doc.strokes[0]?.points[1]).toBe(source[1]);
    expect(doc.strokes[1]?.points[1]).toBe(source[2]);
    expect(doc.strokes[1]?.points[2]).toBe(source[3]);
  });

  it("removes a stroke that is fully under the eraser", () => {
    const short = addStroke(oneLine(), [px(48, 20), px(52, 20)], 0, 2);
    const { doc, nextId } = eraseAlong(short, [[50, 20]], 10, W, H, 3);
    expect(doc.strokes.map((stroke) => stroke.id)).toEqual([1]);
    expect(nextId).toBe(3);
  });

  it("gives a remaining piece a new identifier, also when it is one piece", () => {
    // The eraser takes the right end alone.
    const { doc, nextId } = eraseAlong(oneLine(), [[90, 50]], 10, W, H, 5);
    expect(xs(doc)).toEqual([[10, 80]]);
    expect(doc.strokes[0]?.id).toBe(5);
    expect(nextId).toBe(6);
  });
});

describe("what an erase keeps", () => {
  it("returns the same document when the eraser touches nothing", () => {
    const before = oneLine();
    const result = eraseAlong(before, [[50, 10]], 10, W, H, 2);
    expect(result.doc).toBe(before);
    expect(result.nextId).toBe(2);
    expect(eraseAlong(before, [], 10, W, H, 2).doc).toBe(before);
    expect(eraseAlong(EMPTY_DOC, [[50, 50]], 10, W, H, 2).doc).toBe(EMPTY_DOC);
  });

  it("erases nothing on a tangent touch", () => {
    // The eraser's edge is on the line at one point alone.
    const before = oneLine();
    expect(eraseAlong(before, [[50, 60]], 10, W, H, 2).doc).toBe(before);
  });

  it("keeps the strokes it does not touch, in their sequence", () => {
    let doc = oneLine();
    doc = addStroke(doc, [px(10, 20), px(90, 20)], 3, 2);
    doc = addStroke(doc, [px(10, 80), px(90, 80)], 0, 3);
    const result = eraseAlong(doc, [[50, 20]], 5, W, H, 4);
    // The pieces of stroke 2 stand where stroke 2 stood.
    expect(result.doc.strokes.map((stroke) => stroke.id)).toEqual([1, 4, 5, 3]);
    expect(result.doc.strokes[0]).toBe(doc.strokes[0]);
    expect(result.doc.strokes[3]).toBe(doc.strokes[2]);
  });

  it("gives each piece the color and the group of its stroke", () => {
    let doc = addStroke(EMPTY_DOC, [px(10, 50), px(90, 50)], 4, 1);
    doc = addStroke(doc, [px(10, 20), px(90, 20)], 0, 2);
    doc = makeGroup(doc, [1], "roof");
    const result = eraseAlong(doc, [[50, 50]], 10, W, H, 3);
    const pieces = result.doc.strokes.filter((stroke) => stroke.id >= 3);
    expect(pieces.map((stroke) => stroke.colorIndex)).toEqual([4, 4]);
    expect(result.doc.assignments).toEqual({ 3: "g1", 4: "g1" });
    expect(result.doc.groups).toBe(doc.groups);
    expect(result.doc.relations).toBe(doc.relations);
  });

  it("keeps a group that lost each of its strokes", () => {
    let doc = addStroke(EMPTY_DOC, [px(48, 50), px(52, 50)], 0, 1);
    doc = addStroke(doc, [px(10, 20), px(90, 20)], 0, 2);
    doc = makeGroup(doc, [1], "dot");
    const result = eraseAlong(doc, [[50, 50]], 10, W, H, 3);
    expect(result.doc.strokes.map((stroke) => stroke.id)).toEqual([2]);
    expect(result.doc.assignments).toEqual({});
    expect(result.doc.groups).toEqual([{ id: "g1", label: "dot" }]);
  });

  it("drops a remnant that is shorter than the capture gap", () => {
    // The left remnant is 0.2 pixels long: below the 0.5 pixel gap.
    const before = addStroke(EMPTY_DOC, [px(39.8, 50), px(90, 50)], 0, 1);
    const { doc } = eraseAlong(before, [[50, 50]], 10, W, H, 2);
    expect(xs(doc)).toEqual([[60, 90]]);
  });

  it("removes a one-point stroke under the eraser, and keeps one that is not", () => {
    const dots: SketchDoc = {
      ...EMPTY_DOC,
      strokes: [
        { id: 1, points: [px(50, 50)], colorIndex: 0 },
        { id: 2, points: [px(20, 20)], colorIndex: 0 },
      ],
    };
    const { doc } = eraseAlong(dots, [[50, 50]], 10, W, H, 3);
    expect(doc.strokes.map((stroke) => stroke.id)).toEqual([2]);
    expect(doc.strokes[0]).toBe(dots.strokes[1]);
  });

  it("changes nothing on a second erase along the same path", () => {
    const path: Point[] = [
      [30, 40],
      [50, 50],
      [70, 45],
    ];
    const first = eraseAlong(oneLine(), path, 8, W, H, 2);
    const second = eraseAlong(first.doc, path, 8, W, H, first.nextId);
    expect(second.doc).toBe(first.doc);
  });

  it("gives the same marks in steps as in one move", () => {
    const path: Point[] = [
      [20, 44],
      [35, 52],
      [55, 47],
      [75, 55],
    ];
    const whole = eraseAlong(oneLine(), path, 6, W, H, 2).doc;
    // The canvas applies a move in steps, each from the last sample.
    let stepped = oneLine();
    let nextId = 2;
    for (let index = 1; index < path.length; index += 1) {
      const step = eraseAlong(
        stepped,
        [path[index - 1] as Point, path[index] as Point],
        6,
        W,
        H,
        nextId,
      );
      stepped = step.doc;
      nextId = step.nextId;
    }
    const flat = (doc: SketchDoc): number[] =>
      doc.strokes.flatMap((stroke) => stroke.points.flat());
    expect(flat(stepped)).toHaveLength(flat(whole).length);
    flat(stepped).forEach((value, index) => {
      expect(value).toBeCloseTo(flat(whole)[index] as number, 9);
    });
  });
});

describe("an erased sketch on the wire", () => {
  it("serializes its pieces as ordinary strokes", () => {
    let doc = addStroke(EMPTY_DOC, [px(10, 50), px(90, 50)], 1, 1);
    doc = makeGroup(doc, [1], "line");
    const erased = eraseAlong(doc, [[50, 50]], 10, W, H, 2).doc;
    expect(serialize(erased, ["one"], "")).toEqual({
      impressions: ["one"],
      canvas_strokes: [
        {
          points: [
            [0.1, 0.5],
            [0.4, 0.5],
          ],
          group_id: "g1",
          color: "#bf616a",
        },
        {
          points: [
            [0.6, 0.5],
            [0.9, 0.5],
          ],
          group_id: "g1",
          color: "#bf616a",
        },
      ],
      groups: [{ id: "g1", label: "line" }],
      relations: [],
      pasted_text: null,
    });
  });
});

describe("the eraser's radius", () => {
  it("is wider under a finger", () => {
    expect(eraserRadius("mouse")).toBe(ERASER_RADIUS_PX);
    expect(eraserRadius("pen")).toBe(ERASER_RADIUS_PX);
    expect(eraserRadius("touch")).toBe(ERASER_RADIUS_TOUCH_PX);
    expect(ERASER_RADIUS_TOUCH_PX).toBeGreaterThan(ERASER_RADIUS_PX);
  });
});
