import { describe, expect, it } from "vitest";

import {
  addRelation,
  addStroke,
  canRedo,
  canUndo,
  clearSketch,
  current,
  EMPTY_DOC,
  historyOf,
  makeGroup,
  pushDoc,
  redo,
  undo,
  ungroupStroke,
} from "../../src/sketch/core";

const LINE: [number, number][] = [
  [0.1, 0.1],
  [0.2, 0.2],
];

describe("document reducers", () => {
  it("numbers groups in creation order and never reuses an id", () => {
    let doc = addStroke(EMPTY_DOC, LINE, 0, 1);
    doc = makeGroup(doc, [1], "tower");
    doc = makeGroup(doc, [], "sea");
    expect(doc.groups.map((group) => group.id)).toEqual(["g1", "g2"]);
    expect(doc.assignments[1]).toBe("g1");
  });

  it("ungroups a stroke without touching the group list", () => {
    let doc = addStroke(EMPTY_DOC, LINE, 0, 1);
    doc = makeGroup(doc, [1], "tower");
    doc = ungroupStroke(doc, 1);
    expect(doc.assignments[1]).toBeUndefined();
    expect(doc.groups).toHaveLength(1);
  });

  it("keeps relations through group operations", () => {
    let doc = addStroke(EMPTY_DOC, LINE, 0, 1);
    doc = makeGroup(doc, [1], "tower");
    doc = makeGroup(doc, [], "sea");
    doc = addRelation(doc, "left-of", ["g1", "g2"]);
    doc = ungroupStroke(doc, 1);
    expect(doc.relations).toHaveLength(1);
  });

  it("clears to the empty document as one recorded operation", () => {
    let doc = addStroke(EMPTY_DOC, LINE, 3, 1);
    doc = makeGroup(doc, [1], "tower");
    expect(clearSketch(doc)).toEqual(EMPTY_DOC);
  });
});

describe("the undo history", () => {
  it("moves back and forward over whole-document snapshots", () => {
    const first = addStroke(EMPTY_DOC, LINE, 0, 1);
    const second = addStroke(first, LINE, 1, 2);
    let history = historyOf(EMPTY_DOC);
    history = pushDoc(history, first);
    history = pushDoc(history, second);
    expect(current(history).strokes).toHaveLength(2);
    history = undo(history);
    expect(current(history).strokes).toHaveLength(1);
    history = undo(history);
    expect(current(history).strokes).toHaveLength(0);
    expect(canUndo(history)).toBe(false);
    history = redo(history);
    expect(current(history).strokes).toHaveLength(1);
  });

  it("makes clear undoable", () => {
    const drawn = addStroke(EMPTY_DOC, LINE, 0, 1);
    let history = historyOf(EMPTY_DOC);
    history = pushDoc(history, drawn);
    history = pushDoc(history, clearSketch(drawn));
    expect(current(history).strokes).toHaveLength(0);
    history = undo(history);
    expect(current(history).strokes).toHaveLength(1);
  });

  it("truncates the redo tail on a new operation after undo", () => {
    const first = addStroke(EMPTY_DOC, LINE, 0, 1);
    const second = addStroke(first, LINE, 0, 2);
    let history = historyOf(EMPTY_DOC);
    history = pushDoc(history, first);
    history = pushDoc(history, second);
    history = undo(history);
    const replacement = addStroke(first, LINE, 4, 3);
    history = pushDoc(history, replacement);
    expect(canRedo(history)).toBe(false);
    expect(current(history).strokes.map((stroke) => stroke.id)).toEqual([1, 3]);
  });
});
