/**
 * Labeling parts of the sketch (spec A1 §6, copy per spec BR1 §6):
 * pick the strokes that belong together, then name them. Renders as
 * a fragment — today puts it in a disclosure with the "where things
 * are" row, practice in a card of its own.
 *
 * The label line is this fragment's own state; the selection, the
 * mode, and the document stay in the screen, which owns the canvas
 * they drive.
 */

import { useState } from "react";
import type { SketchDoc } from "../sketch/core";
import { groupDisplay } from "../sketch/palette";

export function GroupControls(props: {
  doc: SketchDoc;
  mode: "draw" | "select";
  selectionSize: number;
  onToggleSelect: () => void;
  onMakeGroup: (label: string) => void;
}): React.JSX.Element {
  const { doc, mode, selectionSize, onToggleSelect, onMakeGroup } = props;
  const [label, setLabel] = useState("");
  const picking = mode === "select";

  const make = () => {
    const trimmed = label.trim();
    if (trimmed !== "" && selectionSize > 0) {
      onMakeGroup(trimmed);
      setLabel("");
    }
  };

  return (
    <>
      <p className="hint">
        Pick the strokes of one thing and name it — “tower”, “water”. Named
        parts are matched to details of the photo, like your words are.
      </p>
      <div>
        <button
          type="button"
          className={picking ? "btn btn-primary" : "btn btn-secondary"}
          disabled={!picking && doc.strokes.length === 0}
          onClick={onToggleSelect}
          aria-pressed={picking}
        >
          {picking ? "Done picking" : "Pick strokes"}
        </button>
      </div>
      {picking ? (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input
            className="input"
            aria-label="Name the picked strokes"
            placeholder={
              selectionSize === 0 ? "Pick strokes first" : "What is it?"
            }
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) {
                event.preventDefault();
                make();
              }
            }}
          />
          <button
            type="button"
            className="btn btn-primary"
            disabled={selectionSize === 0 || label.trim() === ""}
            onClick={make}
          >
            Label
          </button>
        </div>
      ) : null}
      {doc.groups.length === 0 ? null : (
        <ul
          className="stack-sm"
          style={{ margin: 0, padding: 0, listStyle: "none" }}
        >
          {doc.groups.map((group, index) => {
            const count = doc.strokes.filter(
              (stroke) => doc.assignments[stroke.id] === group.id,
            ).length;
            return (
              <li key={group.id} className="row" style={{ gap: 8 }}>
                <span
                  aria-hidden="true"
                  style={{
                    width: 12,
                    height: 12,
                    borderRadius: 4,
                    background: groupDisplay(index),
                    flex: "none",
                  }}
                />
                <span style={{ fontWeight: 600 }}>{group.label}</span>
                <span className="subtle small">
                  {count} {count === 1 ? "stroke" : "strokes"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
