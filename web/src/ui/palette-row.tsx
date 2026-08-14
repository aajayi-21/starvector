/** The eight-swatch palette row (spec C1 §5 as amended, W1 §9). */

import { PALETTE } from "../sketch/palette";

export function PaletteRow(props: {
  colorIndex: number;
  onPick: (index: number) => void;
}): React.JSX.Element {
  return (
    <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
      {PALETTE.map((entry, index) => (
        <button
          key={entry.name}
          type="button"
          title={entry.name}
          aria-label={`color ${entry.name}`}
          aria-pressed={index === props.colorIndex}
          onClick={() => props.onPick(index)}
          style={{
            width: 26,
            height: 26,
            borderRadius: 6,
            cursor: "pointer",
            padding: 0,
            background: entry.display,
            border:
              index === props.colorIndex
                ? "2px solid var(--color-accent)"
                : "2px solid transparent",
          }}
        />
      ))}
    </span>
  );
}
