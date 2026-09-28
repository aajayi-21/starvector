/**
 * The drawing panel shared by today and practice: the color row,
 * undo, redo, clear, the canvas sized to the window, and one hint
 * line. The screens own the document; this panel draws the controls.
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
    <section className="card canvas-panel" aria-label="Sketch">
      <div className="canvas-column">
        <div className="toolbar">
          <PaletteRow
            colorIndex={props.colorIndex}
            onPick={props.onPickColor}
          />
          <span className="spacer" />
          <button
            type="button"
            className="btn btn-secondary btn-icon"
            disabled={!props.canUndo}
            onClick={props.onUndo}
            aria-label="Undo"
            title="Undo"
          >
            <ArrowCounterClockwise size={20} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-icon"
            disabled={!props.canRedo}
            onClick={props.onRedo}
            aria-label="Redo"
            title="Redo"
          >
            <ArrowClockwise size={20} aria-hidden="true" />
          </button>
          <button
            type="button"
            className="btn btn-secondary btn-icon"
            disabled={props.doc.strokes.length === 0}
            onClick={props.onClear}
            aria-label="Clear the sketch"
            title="Clear the sketch"
          >
            <Trash size={20} aria-hidden="true" />
          </button>
        </div>
        <div>
          <SketchCanvas
            doc={props.doc}
            selection={props.selection}
            mode={props.mode}
            colorIndex={props.colorIndex}
            onCommitStroke={props.onCommitStroke}
            onPickStroke={props.onPickStroke}
            disabled={props.disabled}
          />
        </div>
        <p className="hint" aria-live="polite">
          {props.hint}
        </p>
      </div>
    </section>
  );
}
