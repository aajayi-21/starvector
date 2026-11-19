/** The eight-swatch color row (spec C1 §5 as amended, W1 §9). */

import { PALETTE } from "../sketch/palette";

export function PaletteRow(props: {
  colorIndex: number;
  onPick: (index: number) => void;
}): React.JSX.Element {
  return (
    <fieldset className="swatches">
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
            className="swatch"
            style={{ background: entry.display }}
          />
        );
      })}
    </fieldset>
  );
}
