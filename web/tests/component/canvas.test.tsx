import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SketchCanvas } from "../../src/sketch/canvas";
import { addStroke, EMPTY_DOC, type Point } from "../../src/sketch/core";

interface PointerInit {
  x: number;
  y: number;
  pointerId?: number;
  isPrimary?: boolean;
  pointerType?: string;
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
