import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SketchCanvas } from "../../src/sketch/canvas";
import {
  addStroke,
  EMPTY_DOC,
  ERASER_RADIUS_PX,
  type Point,
  type SketchDoc,
  STROKE_WIDTH_PX,
} from "../../src/sketch/core";

interface PointerInit {
  x: number;
  y: number;
  pointerId?: number;
  isPrimary?: boolean;
  pointerType?: string;
  buttons?: number;
}

function firePointer(target: Element, type: string, init: PointerInit): void {
  const event = new MouseEvent(type, {
    bubbles: true,
    clientX: init.x,
    clientY: init.y,
  });
  Object.defineProperties(event, {
    pointerId: { value: init.pointerId ?? 1 },
    isPrimary: { value: init.isPrimary ?? true },
    pointerType: { value: init.pointerType ?? "mouse" },
    buttons: { value: init.buttons ?? 1 },
  });
  target.dispatchEvent(event);
}

function liveLayer(container: HTMLElement): Element {
  const canvases = container.querySelectorAll("canvas");
  const live = canvases[1];
  if (live === undefined) {
    throw new Error("the two canvas layers did not render");
  }
  return live;
}

function drawProps(overrides: Partial<Parameters<typeof SketchCanvas>[0]>) {
  return {
    doc: EMPTY_DOC,
    selection: new Set<number>(),
    mode: "draw" as const,
    colorIndex: 0,
    onCommitStroke: vi.fn(),
    onCommitErase: vi.fn(),
    nextStrokeId: () => 1,
    onPickStroke: vi.fn(),
    ...overrides,
  };
}

describe("SketchCanvas pointer wiring", () => {
  it("commits a drawn stroke as filtered normalized points", () => {
    const onCommitStroke = vi.fn();
    const props = drawProps({ onCommitStroke });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 30, y: 30 });
    firePointer(live, "pointermove", { x: 150, y: 150 });
    firePointer(live, "pointerup", { x: 150, y: 150 });
    expect(onCommitStroke).toHaveBeenCalledTimes(1);
    const points = onCommitStroke.mock.calls[0]?.[0] as Point[];
    expect(points).toEqual([
      [0.1, 0.1],
      [0.5, 0.5],
    ]);
  });

  it("discards a one-point pointercancel and commits a moved one", () => {
    const onCommitStroke = vi.fn();
    const props = drawProps({ onCommitStroke });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 30, y: 30 });
    firePointer(live, "pointercancel", { x: 30, y: 30 });
    expect(onCommitStroke).not.toHaveBeenCalled();
    firePointer(live, "pointerdown", { x: 30, y: 30 });
    firePointer(live, "pointermove", { x: 90, y: 90 });
    firePointer(live, "pointercancel", { x: 90, y: 90 });
    expect(onCommitStroke).toHaveBeenCalledTimes(1);
  });

  it("ignores a second concurrent pointer", () => {
    const onCommitStroke = vi.fn();
    const props = drawProps({ onCommitStroke });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 30, y: 30, pointerId: 1 });
    firePointer(live, "pointerdown", {
      x: 200,
      y: 200,
      pointerId: 2,
      isPrimary: false,
    });
    firePointer(live, "pointermove", { x: 90, y: 90, pointerId: 1 });
    firePointer(live, "pointerup", { x: 90, y: 90, pointerId: 1 });
    expect(onCommitStroke).toHaveBeenCalledTimes(1);
    const points = onCommitStroke.mock.calls[0]?.[0] as Point[];
    expect(points).toHaveLength(2);
  });

  it("picks the nearest stroke in select mode and draws nothing", () => {
    const onCommitStroke = vi.fn();
    const onPickStroke = vi.fn();
    const doc = addStroke(
      EMPTY_DOC,
      [
        [0, 0],
        [1, 0],
      ],
      0,
      1,
    );
    const props = drawProps({
      doc,
      mode: "select",
      onCommitStroke,
      onPickStroke,
    });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 150, y: 5 });
    expect(onPickStroke).toHaveBeenLastCalledWith(1);
    firePointer(live, "pointerdown", { x: 150, y: 50 });
    expect(onPickStroke).toHaveBeenLastCalledWith(null);
    firePointer(live, "pointerup", { x: 150, y: 50 });
    expect(onCommitStroke).not.toHaveBeenCalled();
  });

  it("does nothing while disabled", () => {
    const onCommitStroke = vi.fn();
    const props = drawProps({ onCommitStroke, disabled: true });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 30, y: 30 });
    firePointer(live, "pointermove", { x: 90, y: 90 });
    firePointer(live, "pointerup", { x: 90, y: 90 });
    expect(onCommitStroke).not.toHaveBeenCalled();
  });
});

/** One line across the middle of the 300 by 300 test canvas, with id 1. */
function lineDoc(): SketchDoc {
  return addStroke(
    EMPTY_DOC,
    [
      [0.1, 0.5],
      [0.9, 0.5],
    ],
    0,
    1,
  );
}

describe("SketchCanvas erasing", () => {
  it("gives the screen one cut document for one gesture", () => {
    const onCommitErase = vi.fn();
    const onCommitStroke = vi.fn();
    const props = drawProps({
      doc: lineDoc(),
      mode: "erase",
      onCommitErase,
      onCommitStroke,
      nextStrokeId: () => 5,
    });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    // Down the middle of the canvas, across the line, in three moves.
    firePointer(live, "pointerdown", { x: 150, y: 120 });
    firePointer(live, "pointermove", { x: 150, y: 140 });
    firePointer(live, "pointermove", { x: 150, y: 160 });
    firePointer(live, "pointermove", { x: 150, y: 180 });
    expect(onCommitErase).not.toHaveBeenCalled();
    firePointer(live, "pointerup", { x: 150, y: 180 });
    expect(onCommitErase).toHaveBeenCalledTimes(1);
    expect(onCommitStroke).not.toHaveBeenCalled();
    const [next, nextId] = onCommitErase.mock.calls[0] as [SketchDoc, number];
    expect(next.strokes.map((stroke) => stroke.id)).toEqual([5, 6]);
    expect(nextId).toBe(7);
    // The cut is the eraser's ring and half of the line's width.
    const cut = ERASER_RADIUS_PX + STROKE_WIDTH_PX / 2;
    expect(next.strokes[0]?.points[1]?.[0]).toBeCloseTo((150 - cut) / 300, 9);
    expect(next.strokes[1]?.points[0]?.[0]).toBeCloseTo((150 + cut) / 300, 9);
  });

  it("erases on a tap", () => {
    const onCommitErase = vi.fn();
    const props = drawProps({ doc: lineDoc(), mode: "erase", onCommitErase });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 150, y: 150 });
    firePointer(live, "pointerup", { x: 150, y: 150 });
    expect(onCommitErase).toHaveBeenCalledTimes(1);
    const [next] = onCommitErase.mock.calls[0] as [SketchDoc, number];
    expect(next.strokes).toHaveLength(2);
  });

  it("is wider under a finger", () => {
    const onCommitErase = vi.fn();
    const props = drawProps({ doc: lineDoc(), mode: "erase", onCommitErase });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 150, y: 150, pointerType: "touch" });
    firePointer(live, "pointerup", { x: 150, y: 150, pointerType: "touch" });
    const [next] = onCommitErase.mock.calls[0] as [SketchDoc, number];
    const left = (next.strokes[0]?.points[1]?.[0] ?? 0) * 300;
    expect(150 - left).toBeGreaterThan(ERASER_RADIUS_PX + STROKE_WIDTH_PX / 2);
  });

  it("records no step when the eraser touches nothing", () => {
    const onCommitErase = vi.fn();
    const props = drawProps({ doc: lineDoc(), mode: "erase", onCommitErase });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 150, y: 30 });
    firePointer(live, "pointermove", { x: 200, y: 40 });
    firePointer(live, "pointerup", { x: 200, y: 40 });
    expect(onCommitErase).not.toHaveBeenCalled();
  });

  it("does nothing while disabled", () => {
    const onCommitErase = vi.fn();
    const props = drawProps({
      doc: lineDoc(),
      mode: "erase",
      onCommitErase,
      disabled: true,
    });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 150, y: 150 });
    firePointer(live, "pointerup", { x: 150, y: 150 });
    expect(onCommitErase).not.toHaveBeenCalled();
  });

  it("erases with the eraser end of a stylus while the pen is the tool", () => {
    const onCommitErase = vi.fn();
    const onCommitStroke = vi.fn();
    const props = drawProps({
      doc: lineDoc(),
      mode: "draw",
      onCommitErase,
      onCommitStroke,
    });
    const { container } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    const pen = { pointerType: "pen", buttons: 32 };
    firePointer(live, "pointerdown", { x: 150, y: 130, ...pen });
    firePointer(live, "pointermove", { x: 150, y: 170, ...pen });
    firePointer(live, "pointerup", { x: 150, y: 170, ...pen });
    expect(onCommitErase).toHaveBeenCalledTimes(1);
    expect(onCommitStroke).not.toHaveBeenCalled();
  });

  it("drops an erase when the document moves under it", () => {
    const onCommitErase = vi.fn();
    const props = drawProps({ doc: lineDoc(), mode: "erase", onCommitErase });
    const { container, rerender } = render(<SketchCanvas {...props} />);
    const live = liveLayer(container);
    firePointer(live, "pointerdown", { x: 150, y: 150 });
    firePointer(live, "pointermove", { x: 160, y: 150 });
    // An undo, for example, gives the canvas a different document.
    rerender(<SketchCanvas {...props} doc={EMPTY_DOC} />);
    firePointer(live, "pointerup", { x: 160, y: 150 });
    expect(onCommitErase).not.toHaveBeenCalled();
  });
});
