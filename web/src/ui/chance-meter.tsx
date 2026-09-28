/**
 * One result against chance: a bar from 0% to 100% of the other
 * photos, with a mark at 50% — what guessing gets on average. The
 * one fact that makes a result readable (spec BR1 §6).
 */

import { percentBeaten } from "./format";

export function ChanceMeter(props: { p: number }): React.JSX.Element {
  const percent = percentBeaten(props.p);
  return (
    <div className="stack-sm">
      <div
        className="meter"
        role="img"
        aria-label={`Beat ${percent}% of the other photos. Guessing averages 50%.`}
      >
        <div className="meter-fill" style={{ width: `${percent}%` }} />
        <div className="meter-chance" title="Guessing averages 50%" />
      </div>
      <div className="meter-scale" aria-hidden="true">
        <span>0%</span>
        <span>50% · guessing</span>
        <span>100%</span>
      </div>
    </div>
  );
}
