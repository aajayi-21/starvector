/**
 * The drawing panel shared by today and practice: the color row, the
 * canvas sized to the window, undo, redo, and clear, and one line for a
 * hint that carries information. The screens own the document; this
 * panel draws the controls.
 *
 * The panel has no box of its own. On a wide screen the tools sit over
 * the canvas, at its right edge; on a phone they sit under it, where
 * the colors would not leave them room (styles/play.css). An empty
 * canvas says where to draw, in the canvas itself.
 */

import {
  ArrowClockwise,
  ArrowCounterClockwise,
  Trash,
} from "@phosphor-icons/react";

import { SketchCanvas } from "../sketch/canvas";
import type { Point, SketchDoc } from "../sketch/core";
import { PaletteRow } from "../ui/palette-row";

export function CanvasPanel(props: {
  doc: SketchDoc;
  selection: ReadonlySet<number>;
  mode: "draw" | "select";
  colorIndex: number;
  onPickColor: (index: number) => void;
  onCommitStroke: (points: Point[]) => void;
  onPickStroke: (strokeId: number | null) => void;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  onClear: () => void;
  disabled: boolean;
  hint: string;
}): React.JSX.Element {
  return (
    <section className="canvas-panel" aria-label="Sketch">
      <div className="toolbar">
        <PaletteRow colorIndex={props.colorIndex} onPick={props.onPickColor} />
      </div>
      <div className="canvas-holder">
        <SketchCanvas
          doc={props.doc}
          selection={props.selection}
          mode={props.mode}
          colorIndex={props.colorIndex}
          onCommitStroke={props.onCommitStroke}
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
        {props.hint}
      </p>
    </section>
  );
}
