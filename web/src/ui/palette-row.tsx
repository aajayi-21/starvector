/** The eight-swatch color row (spec C1 §5 as amended, W1 §9). */

import { PALETTE } from "../sketch/palette";

export function PaletteRow(props: {
  colorIndex: number;
  onPick: (index: number) => void;
}): React.JSX.Element {
  return (
    <fieldset
      className="row"
      style={{ gap: 6, border: 0, margin: 0, padding: 0, minWidth: 0 }}
    >
      <legend className="visually-hidden">Color</legend>
      {PALETTE.map((entry, index) => {
        const picked = index === props.colorIndex;
        return (
          <button
            key={entry.name}
            type="button"
            title={entry.name === "ink" ? "white" : entry.name}
            aria-label={`${entry.name === "ink" ? "white" : entry.name} ink`}
            aria-pressed={picked}
            onClick={() => props.onPick(index)}
            style={{
              width: 30,
              height: 30,
              borderRadius: 8,
              cursor: "pointer",
              padding: 0,
              background: entry.display,
              border: "2px solid var(--canvas)",
              boxShadow: picked
                ? "0 0 0 2px var(--surface), 0 0 0 4px var(--accent)"
                : "0 0 0 1px var(--border-strong)",
            }}
          />
        );
      })}
    </fieldset>
  );
}
