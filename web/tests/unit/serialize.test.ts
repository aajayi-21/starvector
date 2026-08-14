import { describe, expect, it } from "vitest";

import {
  addRelation,
  addStroke,
  EMPTY_DOC,
  filterPoints,
  makeGroup,
  serialize,
} from "../../src/sketch/core";

const json = (value: unknown): string => JSON.stringify(value);

describe("serialize — byte-exact wire records", () => {
  it("emits a plain ink line with no color key", () => {
    const points = filterPoints(
      [
        [10, 10],
        [110, 110],
      ],
      200,
      200,
    );
    const doc = addStroke(EMPTY_DOC, points, 0, 1);
    expect(json(serialize(doc, [], ""))).toBe(
      '{"impressions":[],"canvas_strokes":[{"points":[[0.05,0.05],' +
        '[0.55,0.55]],"group_id":null}],"groups":[],"relations":[],' +
        '"pasted_text":null}',
    );
  });

  it("rounds to 4 decimals and clamps to the unit square", () => {
    const points = filterPoints(
      [
        [123.456789, -5],
        [1005, 999.99],
      ],
      1000,
      1000,
    );
    const doc = addStroke(EMPTY_DOC, points, 0, 1);
    const record = serialize(doc, [], "");
    expect(json(record.canvas_strokes[0]?.points)).toBe("[[0.1235,0],[1,1]]");
  });

  it("drops sub-gap points but always keeps the final point", () => {
    const points = filterPoints(
      [
        [0, 0],
        [0.2, 0],
        [0.4, 0],
        [10, 0],
        [10.2, 0],
      ],
      100,
      100,
    );
    expect(json(points)).toBe("[[0,0],[0.1,0],[0.102,0]]");
  });

  it("emits groups, relations, and the color key in fixed order", () => {
    let doc = EMPTY_DOC;
    doc = addStroke(
      doc,
      [
        [0.1, 0.1],
        [0.2, 0.2],
      ],
      0,
      1,
    );
    doc = addStroke(
      doc,
      [
        [0.3, 0.3],
        [0.4, 0.4],
      ],
      5,
      2,
    );
    doc = makeGroup(doc, [1], "tower");
    doc = makeGroup(doc, [], "sea");
    doc = addRelation(doc, "left-of", ["g1", "g2"]);
    expect(json(serialize(doc, ["tall vertical structure"], ""))).toBe(
      '{"impressions":["tall vertical structure"],"canvas_strokes":' +
        '[{"points":[[0.1,0.1],[0.2,0.2]],"group_id":"g1"},' +
        '{"points":[[0.3,0.3],[0.4,0.4]],"group_id":null,' +
        '"color":"#81a1c1"}],"groups":[{"id":"g1","label":"tower"},' +
        '{"id":"g2","label":"sea"}],"relations":[{"relation":"left-of",' +
        '"of":["g1","g2"]}],"pasted_text":null}',
    );
  });

  it("keeps pasted text raw and nulls a blank one", () => {
    expect(serialize(EMPTY_DOC, [], "  hi  ").pasted_text).toBe("  hi  ");
    expect(serialize(EMPTY_DOC, [], "   ").pasted_text).toBeNull();
    expect(serialize(EMPTY_DOC, [], "").pasted_text).toBeNull();
  });

  it("always carries all five record keys in the frozen order", () => {
    const record = serialize(EMPTY_DOC, [], "");
    expect(Object.keys(record)).toEqual([
      "impressions",
      "canvas_strokes",
      "groups",
      "relations",
      "pasted_text",
    ]);
  });

  it("orders stroke keys as points, group_id, then color", () => {
    let doc = addStroke(
      EMPTY_DOC,
      [
        [0, 0],
        [0.5, 0.5],
      ],
      2,
      1,
    );
    doc = makeGroup(doc, [1], "arc");
    const stroke = serialize(doc, [], "").canvas_strokes[0];
    expect(Object.keys(stroke ?? {})).toEqual(["points", "group_id", "color"]);
    const inkDoc = addStroke(
      EMPTY_DOC,
      [
        [0, 0],
        [0.5, 0.5],
      ],
      0,
      1,
    );
    const inkStroke = serialize(inkDoc, [], "").canvas_strokes[0];
    expect(Object.keys(inkStroke ?? {})).toEqual(["points", "group_id"]);
  });
});
