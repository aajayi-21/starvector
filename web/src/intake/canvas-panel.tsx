/**
 * The drawing panel shared by today and practice: the color row, the
 * canvas sized to the window, the eraser, undo, redo, and clear, and
 * one line for a hint that carries information. The screens own the
 * document; this panel draws the controls.
 *
 * The panel owns one thing: which tool the pointer is, the pen or the
 * eraser. The eraser cuts the lines where it passes (sketch/core.ts,
 * `eraseAlong`), and the screen gets one document for each gesture.
 * Picking a color gives the pen back.
 *
 * The panel has no box of its own. On a wide screen the tools sit over
 * the canvas, at its right edge; on a phone they sit under it, where
 * the colors would not leave them room (styles/play.css). An empty
 * canvas says where to draw, in the canvas itself.
 */

import {
  ArrowClockwise,
  ArrowCounterClockwise,
  Eraser,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { SketchCanvas } from "../sketch/canvas";
import type { Point, SketchDoc } from "../sketch/core";
import { PaletteRow } from "../ui/palette-row";

/** What the hint line says while the eraser is the tool. */
export const ERASER_HINT =
  "Erasing. Press the eraser again, or pick a color, to draw.";

export function CanvasPanel(props: {
  doc: SketchDoc;
  selection: ReadonlySet<number>;
  mode: "draw" | "select";
  colorIndex: number;
  onPickColor: (index: number) => void;
  onCommitStroke: (points: Point[]) => void;
  /** One erase gesture: the cut document, and the next unused stroke id. */
  onCommitErase: (next: SketchDoc, nextStrokeId: number) => void;
  /** The next unused stroke identifier. */
  nextStrokeId: () => number;
  onPickStroke: (strokeId: number | null) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onClear: () => void;
  disabled: boolean;
  hint: string;
}): React.JSX.Element {
  const [erasing, setErasing] = useState(false);
  const empty = props.doc.strokes.length === 0;
  const selecting = props.mode === "select";
  // The eraser has nothing to do on an empty sketch, and picking lines
  // is its own use of the pointer: each gives the pen back.
  useEffect(() => {
    if (empty || selecting) {
      setErasing(false);
    }
  }, [empty, selecting]);
  const eraserOn = erasing && !empty && !selecting && !props.disabled;
  return (
    <section className="canvas-panel" aria-label="Sketch">
      <div className="toolbar">
        <PaletteRow
          colorIndex={props.colorIndex}
          onPick={(index) => {
            setErasing(false);
            props.onPickColor(index);
          }}
        />
      </div>
      <div className="canvas-holder">
        <SketchCanvas
          doc={props.doc}
          selection={props.selection}
          mode={selecting ? "select" : eraserOn ? "erase" : "draw"}
          colorIndex={props.colorIndex}
          onCommitStroke={props.onCommitStroke}
          onCommitErase={props.onCommitErase}
          nextStrokeId={props.nextStrokeId}
          onPickStroke={props.onPickStroke}
          disabled={props.disabled}
        />
        {props.doc.strokes.length === 0 && !props.disabled ? (
          <p className="canvas-empty atlas" aria-hidden="true">
            Draw here
          </p>
        ) : null}
      </div>
      <div className="tools">
        <button
          type="button"
          className="btn btn-icon tool tool-eraser"
          disabled={empty || selecting || props.disabled}
          onClick={() => setErasing((on) => !on)}
          aria-pressed={eraserOn}
          aria-label="Eraser"
          title="Eraser"
        >
          <Eraser size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-icon tool"
          disabled={!props.canUndo}
          onClick={props.onUndo}
          aria-label="Undo"
          title="Undo"
        >
          <ArrowCounterClockwise size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-icon tool"
          disabled={!props.canRedo}
          onClick={props.onRedo}
          aria-label="Redo"
          title="Redo"
        >
          <ArrowClockwise size={20} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="btn btn-icon tool"
          disabled={props.doc.strokes.length === 0}
          onClick={props.onClear}
          aria-label="Clear the sketch"
          title="Clear the sketch"
        >
          <Trash size={20} aria-hidden="true" />
        </button>
      </div>
      <p className="hint canvas-hint" aria-live="polite">
        {eraserOn ? ERASER_HINT : props.hint}
      </p>
    </section>
  );
}
