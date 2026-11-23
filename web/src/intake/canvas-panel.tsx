/**
 * The drawing panel shared by today and practice (the Studio design of
 * 2026-11-21): one rail of tools on the edge of the canvas, the canvas
 * as tall as the window, and one line under it for a hint that carries
 * information. The screens own the document; this panel draws the
 * controls.
 *
 * The rail holds the pen and the eraser, then undo, redo, and clear,
 * then the colors. The pen and the eraser are two tools, and one of
 * them is lit. The panel owns which one the pointer is, and how large
 * the eraser is. The eraser cuts the lines where it passes
 * (sketch/core.ts, `eraseAlong`), and the screen gets one document for
 * each gesture. Picking a color gives the pen back. While the eraser
 * is the tool, the edge of the canvas is dashed and its three sizes
 * stand on the hint line.
 *
 * The panel has no box of its own. On a phone the colors and the tools
 * sit under the canvas (styles/play.css). An empty canvas says where
 * to draw, and what to draw, in the canvas itself.
 */

import {
  ArrowClockwise,
  ArrowCounterClockwise,
  Eraser,
  PencilSimple,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";

import { SketchCanvas } from "../sketch/canvas";
import type { Point, SketchDoc } from "../sketch/core";
import { ERASER_SCALE_START, ERASER_SCALES } from "../sketch/core";
import { PaletteRow } from "../ui/palette-row";

/** What the hint line says while the eraser is the tool. */
export const ERASER_HINT = "Erasing. Pick the pen or a color to draw.";

const ERASER_SIZE_NAMES = ["Small", "Middle", "Large"] as const;

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
  /** What to draw, said in the empty canvas, under "Draw here". */
  emptyNote?: string;
}): React.JSX.Element {
  const [erasing, setErasing] = useState(false);
  const [eraserScale, setEraserScale] = useState<number>(ERASER_SCALE_START);
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
  const penOn = !eraserOn && !selecting && !props.disabled;
  return (
    <section
      className={eraserOn ? "canvas-panel is-erasing" : "canvas-panel"}
      aria-label="Sketch"
    >
      <div className="tool-rail">
        <fieldset className="tools">
          <legend className="visually-hidden">Tools</legend>
          <button
            type="button"
            className="btn btn-icon tool tool-pen"
            disabled={selecting || props.disabled}
            onClick={() => setErasing(false)}
            aria-pressed={penOn}
            aria-label="Pen"
            title="Pen"
          >
            <PencilSimple size={20} aria-hidden="true" />
          </button>
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
        </fieldset>
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
          eraserScale={eraserScale}
        />
        {empty && !props.disabled ? (
          <div className="canvas-empty">
            <p className="canvas-empty-here atlas" aria-hidden="true">
              Draw here
            </p>
            {props.emptyNote === undefined ? null : (
              <p className="canvas-empty-note">{props.emptyNote}</p>
            )}
          </div>
        ) : null}
      </div>
      <div className="canvas-foot">
        {eraserOn ? (
          <fieldset className="eraser-sizes">
            <legend className="visually-hidden">Eraser size</legend>
            {ERASER_SCALES.map((scale, index) => (
              <button
                key={scale}
                type="button"
                className="eraser-size"
                // The group says "Eraser size"; the name is the size alone, so
                // "Eraser" names one button on the screen.
                aria-label={ERASER_SIZE_NAMES[index]}
                aria-pressed={scale === eraserScale}
                onClick={() => setEraserScale(scale)}
              >
                <span
                  className="eraser-size-ring"
                  style={{ "--eraser-size": index } as React.CSSProperties}
                />
              </button>
            ))}
          </fieldset>
        ) : null}
        <p className="hint canvas-hint" aria-live="polite">
          {eraserOn ? ERASER_HINT : props.hint}
        </p>
      </div>
    </section>
  );
}
