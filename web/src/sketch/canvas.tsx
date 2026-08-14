/**
 * The canvas DOM adapter (spec W1 §9): two stacked canvases over a
 * square container. The committed layer replays the document; the
 * live layer draws the active stroke once for each animation frame.
 * Pointer Events alone, capture-time filtering, DPR-correct backing
 * stores. Committed documents alone touch React — points in flight
 * live in refs.
 */

import { useEffect, useRef } from "react";

import type { Point, SketchDoc } from "./core";
import {
  filterPoints,
  hitTest,
  SELECT_TOLERANCE_TOUCH_PX,
  STROKE_WIDTH_PX,
  selectTolerance,
} from "./core";
import { displayOf, groupDisplay } from "./palette";

const HALO_WIDTH_PX = 9;
const SELECTION_HALO = "#88c0d0";

export type CanvasMode = "draw" | "select";

export interface SketchCanvasProps {
  doc: SketchDoc;
  selection: ReadonlySet<number>;
  mode: CanvasMode;
  colorIndex: number;
  onCommitStroke: (points: Point[]) => void;
  onPickStroke: (strokeId: number | null) => void;
  disabled?: boolean;
}

interface CssSize {
  width: number;
  height: number;
}

interface ActiveStroke {
  pointerId: number;
  rawCssPoints: Point[];
}

function polyline(
  context: CanvasRenderingContext2D,
  points: ReadonlyArray<Point>,
  cssSize: CssSize,
  color: string,
  widthPx: number,
): void {
  context.beginPath();
  context.lineWidth = widthPx;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = color;
  points.forEach(([x, y], index) => {
    const cssX = x * cssSize.width;
    const cssY = y * cssSize.height;
    if (index === 0) {
      context.moveTo(cssX, cssY);
    } else {
      context.lineTo(cssX, cssY);
    }
  });
  context.stroke();
}

function drawDoc(
  context: CanvasRenderingContext2D,
  doc: SketchDoc,
  selection: ReadonlySet<number>,
  cssSize: CssSize,
): void {
  context.clearRect(0, 0, cssSize.width, cssSize.height);
  const groupIndex = new Map(
    doc.groups.map((group, index) => [group.id, index]),
  );
  for (const stroke of doc.strokes) {
    // Halo precedence: selected above grouped; the stroke keeps its
    // own color so what is on screen is what the model sees, up to
    // the halo.
    const groupId = doc.assignments[stroke.id];
    if (selection.has(stroke.id)) {
      polyline(context, stroke.points, cssSize, SELECTION_HALO, HALO_WIDTH_PX);
    } else if (groupId !== undefined) {
      const hue = groupDisplay(groupIndex.get(groupId) ?? 0);
      polyline(context, stroke.points, cssSize, hue, HALO_WIDTH_PX);
    }
    polyline(
      context,
      stroke.points,
      cssSize,
      displayOf(stroke.colorIndex),
      STROKE_WIDTH_PX,
    );
  }
}

function sizeBackingStore(
  canvas: HTMLCanvasElement,
  entry: ResizeObserverEntry | null,
  cssSize: CssSize,
): CanvasRenderingContext2D | null {
  const ratio = window.devicePixelRatio || 1;
  const boxes = entry?.devicePixelContentBoxSize;
  const box = boxes?.[0];
  const deviceWidth = box?.inlineSize ?? Math.round(cssSize.width * ratio);
  const deviceHeight = box?.blockSize ?? Math.round(cssSize.height * ratio);
  canvas.width = Math.max(1, deviceWidth);
  canvas.height = Math.max(1, deviceHeight);
  const context = canvas.getContext("2d");
  if (context !== null) {
    const scaleX = canvas.width / Math.max(1, cssSize.width);
    const scaleY = canvas.height / Math.max(1, cssSize.height);
    context.setTransform(scaleX, 0, 0, scaleY, 0, 0);
  }
  return context;
}

export function SketchCanvas(props: SketchCanvasProps): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const committedRef = useRef<HTMLCanvasElement | null>(null);
  const liveRef = useRef<HTMLCanvasElement | null>(null);
  const sizeRef = useRef<CssSize>({ width: 0, height: 0 });
  const activeRef = useRef<ActiveStroke | null>(null);
  const framePending = useRef(false);
  // Handlers attach one time and read the latest props through this ref.
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    const container = containerRef.current;
    const committed = committedRef.current;
    const live = liveRef.current;
    if (container === null || committed === null || live === null) {
      return;
    }

    const redrawCommitted = () => {
      const context = committed.getContext("2d");
      if (context !== null) {
        drawDoc(
          context,
          propsRef.current.doc,
          propsRef.current.selection,
          sizeRef.current,
        );
      }
    };

    const flushLive = () => {
      framePending.current = false;
      const context = live.getContext("2d");
      const active = activeRef.current;
      if (context === null) {
        return;
      }
      context.clearRect(0, 0, sizeRef.current.width, sizeRef.current.height);
      if (active !== null && active.rawCssPoints.length > 1) {
        const normalized = filterPoints(
          active.rawCssPoints,
          Math.max(1, sizeRef.current.width),
          Math.max(1, sizeRef.current.height),
        );
        polyline(
          context,
          normalized,
          sizeRef.current,
          displayOf(propsRef.current.colorIndex),
          STROKE_WIDTH_PX,
        );
      }
    };

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0] ?? null;
      const rect = entry?.contentRect;
      sizeRef.current = {
        width: rect?.width ?? container.clientWidth,
        height: rect?.height ?? container.clientHeight,
      };
      sizeBackingStore(committed, entry, sizeRef.current);
      sizeBackingStore(live, entry, sizeRef.current);
      redrawCommitted();
      flushLive();
    });
    observer.observe(container);

    const cssPoint = (event: PointerEvent): Point => {
      const rect = live.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top];
    };

    const endStroke = (event: PointerEvent, commit: boolean) => {
      const active = activeRef.current;
      if (active === null || active.pointerId !== event.pointerId) {
        return;
      }
      activeRef.current = null;
      if (commit) {
        const points = filterPoints(
          active.rawCssPoints,
          Math.max(1, sizeRef.current.width),
          Math.max(1, sizeRef.current.height),
        );
        if (points.length >= 2) {
          propsRef.current.onCommitStroke(points);
        }
      }
      const context = live.getContext("2d");
      context?.clearRect(0, 0, sizeRef.current.width, sizeRef.current.height);
    };

    const onPointerDown = (event: PointerEvent) => {
      const latest = propsRef.current;
      if (latest.disabled === true || !event.isPrimary) {
        return;
      }
      if (activeRef.current !== null) {
        // Palm defense: one stroke at a time.
        return;
      }
      if (latest.mode === "select") {
        const tolerance =
          event.pointerType === "touch"
            ? SELECT_TOLERANCE_TOUCH_PX
            : selectTolerance(STROKE_WIDTH_PX);
        const hit = hitTest(
          latest.doc,
          cssPoint(event),
          Math.max(1, sizeRef.current.width),
          Math.max(1, sizeRef.current.height),
          tolerance,
        );
        latest.onPickStroke(hit);
        return;
      }
      live.setPointerCapture?.(event.pointerId);
      activeRef.current = {
        pointerId: event.pointerId,
        rawCssPoints: [cssPoint(event)],
      };
    };

    const onPointerMove = (event: PointerEvent) => {
      const active = activeRef.current;
      if (active === null || active.pointerId !== event.pointerId) {
        return;
      }
      // Safari's first coalesced-events implementation omits fields
      // other than the coordinates on coalesced entries — read
      // clientX/clientY against the bounding rect alone.
      const rect = live.getBoundingClientRect();
      const entries = event.getCoalescedEvents?.() ?? [event];
      for (const entry of entries) {
        active.rawCssPoints.push([
          entry.clientX - rect.left,
          entry.clientY - rect.top,
        ]);
      }
      if (!framePending.current) {
        framePending.current = true;
        requestAnimationFrame(flushLive);
      }
    };

    const onPointerUp = (event: PointerEvent) => endStroke(event, true);
    // On cancel, commit at two or more points, else discard — the
    // filter decides; no stroke stays open (§9).
    const onPointerCancel = (event: PointerEvent) => endStroke(event, true);
    const onLostCapture = () => {
      // Defensive: capture went away without up/cancel reaching us.
      activeRef.current = null;
    };
    const onContextMenu = (event: Event) => event.preventDefault();

    live.addEventListener("pointerdown", onPointerDown);
    live.addEventListener("pointermove", onPointerMove);
    live.addEventListener("pointerup", onPointerUp);
    live.addEventListener("pointercancel", onPointerCancel);
    live.addEventListener("lostpointercapture", onLostCapture);
    live.addEventListener("contextmenu", onContextMenu);

    return () => {
      observer.disconnect();
      live.removeEventListener("pointerdown", onPointerDown);
      live.removeEventListener("pointermove", onPointerMove);
      live.removeEventListener("pointerup", onPointerUp);
      live.removeEventListener("pointercancel", onPointerCancel);
      live.removeEventListener("lostpointercapture", onLostCapture);
      live.removeEventListener("contextmenu", onContextMenu);
    };
  }, []);

  // Redraw the committed layer when the document or selection moves.
  useEffect(() => {
    const committed = committedRef.current;
    const context = committed?.getContext("2d") ?? null;
    if (context !== null) {
      drawDoc(context, props.doc, props.selection, sizeRef.current);
    }
  }, [props.doc, props.selection]);

  const layer: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
  };
  return (
    <div
      ref={containerRef}
      data-testid="sketch-canvas"
      style={{
        position: "relative",
        aspectRatio: "1 / 1",
        width: "100%",
        background: "#272c37",
        border: "1px solid var(--color-divider)",
        borderRadius: 8,
        overflow: "hidden",
        cursor: props.mode === "select" ? "pointer" : "crosshair",
      }}
    >
      <canvas ref={committedRef} style={layer} />
      <canvas
        ref={liveRef}
        style={{
          ...layer,
          touchAction: "none",
          userSelect: "none",
          WebkitUserSelect: "none",
        }}
      />
    </div>
  );
}

/** Read-only replay of a stored wire record (the reveal screen). */
export function ReplayCanvas(props: {
  strokes: ReadonlyArray<{
    points: ReadonlyArray<Point>;
    color?: string | undefined;
  }>;
}): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const strokesRef = useRef(props.strokes);
  strokesRef.current = props.strokes;

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (container === null || canvas === null) {
      return;
    }
    const draw = (entry: ResizeObserverEntry | null, size: CssSize) => {
      const context = sizeBackingStore(canvas, entry, size);
      if (context === null) {
        return;
      }
      context.clearRect(0, 0, size.width, size.height);
      for (const stroke of strokesRef.current) {
        polyline(
          context,
          stroke.points,
          size,
          stroke.color ?? "#eceff4",
          STROKE_WIDTH_PX,
        );
      }
    };
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0] ?? null;
      const rect = entry?.contentRect;
      draw(entry, {
        width: rect?.width ?? container.clientWidth,
        height: rect?.height ?? container.clientHeight,
      });
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (container === null || canvas === null) {
      return;
    }
    const size = {
      width: container.clientWidth,
      height: container.clientHeight,
    };
    const context = canvas.getContext("2d");
    if (context === null) {
      return;
    }
    context.clearRect(0, 0, size.width, size.height);
    for (const stroke of props.strokes) {
      polyline(
        context,
        stroke.points,
        size,
        stroke.color ?? "#eceff4",
        STROKE_WIDTH_PX,
      );
    }
  }, [props.strokes]);

  return (
    <div
      ref={containerRef}
      style={{
        aspectRatio: "1 / 1",
        width: "100%",
        background: "#272c37",
        borderRadius: 8,
        overflow: "hidden",
      }}
    >
      <canvas
        ref={canvasRef}
        style={{ width: "100%", height: "100%", display: "block" }}
      />
    </div>
  );
}
