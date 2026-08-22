/**
 * The group controls (spec A1 §6): extracted from the daily screen
 * so practice mounts the same input. Renders as a fragment — the
 * daily screen composes it into one card with the relations
 * section, and practice wraps it in a card of its own.
 *
 * The label line is this fragment's own state; the selection, the
 * mode, and the document stay in the screen, which owns the canvas
 * they drive.
 */

import { useState } from "react";
import type { SketchDoc } from "../sketch/core";
import { groupDisplay } from "../sketch/palette";
import { Kicker } from "../ui/kicker";

export function GroupControls(props: {
  doc: SketchDoc;
  mode: "draw" | "select";
  selectionSize: number;
  onToggleSelect: () => void;
  onMakeGroup: (label: string) => void;
}): React.JSX.Element {
  const { doc, mode, selectionSize, onToggleSelect, onMakeGroup } = props;
  const [label, setLabel] = useState("");

  return (
    <>
      <Kicker>Groups on the sketch</Kicker>
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="button"
          className={
            mode === "select" ? "btn btn-primary" : "btn btn-secondary"
          }
          onClick={onToggleSelect}
        >
          {mode === "select" ? "Done selecting" : "Select strokes"}
        </button>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          className="input"
          placeholder="what is it? e.g. tower"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          style={{ flex: 1 }}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={selectionSize === 0 || label.trim() === ""}
          onClick={() => {
            const trimmed = label.trim();
            if (trimmed !== "" && selectionSize > 0) {
              onMakeGroup(trimmed);
              setLabel("");
            }
          }}
        >
          Group
        </button>
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          fontSize: 13,
        }}
      >
        {doc.groups.map((group, index) => (
          <div
            key={group.id}
            style={{ display: "flex", alignItems: "center", gap: 8 }}
          >
            <span
              style={{
                width: 10,
                height: 10,
                borderRadius: 3,
                background: groupDisplay(index),
              }}
            />
            {group.label}{" "}
            <span style={{ color: "var(--color-neutral-600)", fontSize: 11 }}>
              {group.id} ·{" "}
              {
                doc.strokes.filter(
                  (stroke) => doc.assignments[stroke.id] === group.id,
                ).length
              }{" "}
              strokes
            </span>
          </div>
        ))}
      </div>
    </>
  );
}
