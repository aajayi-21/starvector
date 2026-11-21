/**
 * The canvas DOM adapter (spec W1 §9): two stacked canvases over a
 * square container. The committed layer replays the document; the
 * live layer draws the active stroke once for each animation frame.
 * Pointer Events alone, capture-time filtering, DPR-correct backing
 * stores. Committed documents alone touch React — points in flight
 * live in refs.
 *
 * An erase is one gesture too. While the eraser moves, the adapter
 * holds a provisional document in a ref and draws it on the committed
 * layer, so the player sees the marks go. At the end of the gesture it
 * gives the screen one document: one step of the undo history.
 */

import { useEffect, useRef } from "react";

import type { Point, SketchDoc } from "./core";
import {
  eraseAlong,
  eraserRadius,
  filterPoints,
  hitTest,
  MIN_POINT_GAP_PX,
  SELECT_TOLERANCE_TOUCH_PX,
  STROKE_WIDTH_PX,
  selectTolerance,
} from "./core";
import { displayOf, groupDisplay } from "./palette";

const HALO_WIDTH_PX = 9;
const SELECTION_HALO = "#88c0d0";
const ERASER_RING = "#eceff4";
/** The eraser button of a stylus, in PointerEvent.buttons. */
const PEN_ERASER_BUTTON = 32;

export type CanvasMode = "draw" | "erase" | "select";

export interface SketchCanvasProps {
  doc: SketchDoc;
  selection: ReadonlySet<number>;
  mode: CanvasMode;
  colorIndex: number;
  onCommitStroke: (points: Point[]) => void;
  /**
   * One erase gesture, at its end: the document with the marks cut,
   * and the first stroke identifier that the cut did not use. Not
   * sent when the eraser touched nothing.
   */
  onCommitErase: (next: SketchDoc, nextStrokeId: number) => void;
  /** The next unused stroke identifier, read at the start of an erase. */
  nextStrokeId: () => number;
  onPickStroke: (strokeId: number | null) => void;
  disabled?: boolean;
}

interface CssSize {
  width: number;
  height: number;
}

interface ActiveStroke {
  kind: "draw";
  pointerId: number;
  rawCssPoints: Point[];
}

interface ActiveErase {
  kind: "erase";
  pointerId: number;
  /** The document of the props when the gesture started. */
  base: SketchDoc;
  /** The provisional document: the base with the marks cut so far. */
  doc: SketchDoc;
  nextId: number;
  /** The cut radius: the eraser's ring and half of a stroke's width. */
  radius: number;
  /** The last sample that was applied, or null before the first. */
  last: Point | null;
  /** The samples that wait for the next animation frame. */
  pending: Point[];
}

/** Where the eraser's ring is drawn on the live layer. */
interface Ring {
  at: Point;
  radius: number;
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
  const activeRef = useRef<ActiveStroke | ActiveErase | null>(null);
  const ringRef = useRef<Ring | null>(null);
  const framePending = useRef(false);
  // The screen's redraw of the committed layer and the eraser's drop of
  // a gesture, for the effects below the handlers.
  const dropEraseRef = useRef<() => void>(() => {});
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

    /** Cut the waiting samples out of the provisional document. */
    const applyErase = (erase: ActiveErase) => {
      if (erase.pending.length === 0) {
        return;
      }
      const path =
        erase.last === null ? erase.pending : [erase.last, ...erase.pending];
      erase.last = erase.pending[erase.pending.length - 1] ?? erase.last;
      erase.pending = [];
      const result = eraseAlong(
        erase.doc,
        path,
        erase.radius,
        Math.max(1, sizeRef.current.width),
        Math.max(1, sizeRef.current.height),
        erase.nextId,
      );
      if (result.doc === erase.doc) {
        return;
      }
      erase.doc = result.doc;
      erase.nextId = result.nextId;
      // The committed layer shows the cut as it is: what the player
      // sees is what the document holds.
      const context = committed.getContext("2d");
      if (context !== null) {
        drawDoc(
          context,
          erase.doc,
          propsRef.current.selection,
          sizeRef.current,
        );
      }
    };

    const flushLive = () => {
      framePending.current = false;
      const context = live.getContext("2d");
      const active = activeRef.current;
      if (active !== null && active.kind === "erase") {
        applyErase(active);
      }
      if (context === null) {
        return;
      }
      context.clearRect(0, 0, sizeRef.current.width, sizeRef.current.height);
      if (
        active !== null &&
        active.kind === "draw" &&
        active.rawCssPoints.length > 1
      ) {
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
      const ring = ringRef.current;
      if (ring !== null) {
        context.beginPath();
        context.lineWidth = 1;
        context.strokeStyle = ERASER_RING;
        context.arc(ring.at[0], ring.at[1], ring.radius, 0, Math.PI * 2);
        context.stroke();
      }
    };

    const scheduleFlush = () => {
      if (!framePending.current) {
        framePending.current = true;
        requestAnimationFrame(flushLive);
      }
    };

    /** Drop an erase in flight: the committed layer shows the props again. */
    const dropErase = () => {
      const active = activeRef.current;
      if (active === null || active.kind !== "erase") {
        return;
      }
      activeRef.current = null;
      ringRef.current = null;
      redrawCommitted();
      scheduleFlush();
    };
    dropEraseRef.current = dropErase;

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
      if (active.kind === "erase") {
        // The samples of the last frame are part of the gesture.
        applyErase(active);
        if (event.pointerType === "touch") {
          // A finger that left the screen has no place for a ring.
          ringRef.current = null;
        }
        flushLive();
        if (active.doc !== active.base) {
          // One gesture is one document: one step of the undo history.
          propsRef.current.onCommitErase(active.doc, active.nextId);
        }
        return;
      }
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
      // The eraser end of a stylus erases with no change of tool.
      const penEraser =
        event.pointerType === "pen" &&
        (event.buttons & PEN_ERASER_BUTTON) !== 0;
      if (latest.mode === "erase" || penEraser) {
        const at = cssPoint(event);
        const ringRadius = eraserRadius(event.pointerType);
        activeRef.current = {
          kind: "erase",
          pointerId: event.pointerId,
          base: latest.doc,
          doc: latest.doc,
          nextId: latest.nextStrokeId(),
          // No round end of a cut stroke stays inside the ring.
          radius: ringRadius + STROKE_WIDTH_PX / 2,
          last: null,
          pending: [at],
        };
        ringRef.current = { at, radius: ringRadius };
        scheduleFlush();
        return;
      }
      activeRef.current = {
        kind: "draw",
        pointerId: event.pointerId,
        rawCssPoints: [cssPoint(event)],
      };
    };

    const onPointerMove = (event: PointerEvent) => {
      const active = activeRef.current;
      if (active === null) {
        // No gesture: the ring follows a mouse or a pen over the
        // canvas while the eraser is the tool.
        const latest = propsRef.current;
        if (
          latest.mode === "erase" &&
          latest.disabled !== true &&
          event.pointerType !== "touch"
        ) {
          ringRef.current = {
            at: cssPoint(event),
            radius: eraserRadius(event.pointerType),
          };
          scheduleFlush();
        }
        return;
      }
      if (active.pointerId !== event.pointerId) {
        return;
      }
      // Safari's first coalesced-events implementation omits fields
      // other than the coordinates on coalesced entries — read
      // clientX/clientY against the bounding rect alone.
      const rect = live.getBoundingClientRect();
      const entries = event.getCoalescedEvents?.() ?? [event];
      if (active.kind === "erase") {
        for (const entry of entries) {
          const at: Point = [
            entry.clientX - rect.left,
            entry.clientY - rect.top,
          ];
          const before =
            active.pending[active.pending.length - 1] ?? active.last;
          // A sample that did not move adds no cut.
          if (
            before === null ||
            Math.hypot(at[0] - before[0], at[1] - before[1]) >= MIN_POINT_GAP_PX
          ) {
            active.pending.push(at);
          }
          if (ringRef.current !== null) {
            ringRef.current = { ...ringRef.current, at };
          }
        }
        scheduleFlush();
        return;
      }
      for (const entry of entries) {
        active.rawCssPoints.push([
          entry.clientX - rect.left,
          entry.clientY - rect.top,
        ]);
      }
      scheduleFlush();
    };

    const onPointerUp = (event: PointerEvent) => endStroke(event, true);
    // On cancel, commit at two or more points, else discard — the
    // filter decides; no stroke stays open (§9).
    const onPointerCancel = (event: PointerEvent) => endStroke(event, true);
    const onLostCapture = () => {
      // Defensive: capture went away without up/cancel reaching us. An
      // erase in flight is dropped, and its marks come back.
      dropErase();
      activeRef.current = null;
    };
    const onPointerLeave = () => {
      if (activeRef.current === null && ringRef.current !== null) {
        ringRef.current = null;
        scheduleFlush();
      }
    };
    const onContextMenu = (event: Event) => event.preventDefault();

    live.addEventListener("pointerdown", onPointerDown);
    live.addEventListener("pointermove", onPointerMove);
    live.addEventListener("pointerup", onPointerUp);
    live.addEventListener("pointercancel", onPointerCancel);
    live.addEventListener("lostpointercapture", onLostCapture);
    live.addEventListener("pointerleave", onPointerLeave);
    live.addEventListener("contextmenu", onContextMenu);

    return () => {
      observer.disconnect();
      live.removeEventListener("pointerdown", onPointerDown);
      live.removeEventListener("pointermove", onPointerMove);
      live.removeEventListener("pointerup", onPointerUp);
      live.removeEventListener("pointercancel", onPointerCancel);
      live.removeEventListener("lostpointercapture", onLostCapture);
      live.removeEventListener("pointerleave", onPointerLeave);
      live.removeEventListener("contextmenu", onContextMenu);
    };
  }, []);

  // Redraw the committed layer when the document or selection moves. A
  // document that moves under an erase in flight (an undo, for example)
  // ends that erase: its cut was of a document that is gone.
  useEffect(() => {
    const active = activeRef.current;
    if (
      active !== null &&
      active.kind === "erase" &&
      active.base !== props.doc
    ) {
      dropEraseRef.current();
    }
    const committed = committedRef.current;
    const context = committed?.getContext("2d") ?? null;
    if (context !== null) {
      drawDoc(context, props.doc, props.selection, sizeRef.current);
    }
  }, [props.doc, props.selection]);

  // The eraser's ring and an erase in flight go when the tool changes
  // or the canvas turns off.
  useEffect(() => {
    if (props.mode === "erase" && props.disabled !== true) {
      return;
    }
    dropEraseRef.current();
    if (ringRef.current !== null && activeRef.current === null) {
      ringRef.current = null;
      const live = liveRef.current;
      const context = live?.getContext("2d") ?? null;
      context?.clearRect(0, 0, sizeRef.current.width, sizeRef.current.height);
    }
  }, [props.mode, props.disabled]);

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
        background: "var(--canvas, #1f2430)",
        border: "1px solid var(--canvas-border, #2e3544)",
        borderRadius: 2,
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
        background: "var(--canvas, #1f2430)",
        borderRadius: 2,
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
