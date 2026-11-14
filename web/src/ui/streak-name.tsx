/**
 * A username with its streak mark (spec H1 §4). Tier 0 draws the
 * plain text. A marked name adds a visually hidden streak label, so
 * the mark is never the only sign of the streak.
 */

import { streakLabel, streakTier } from "./streak";

export function StreakName(props: {
  streak: number;
  children: React.ReactNode;
}): React.JSX.Element {
  const tier = streakTier(props.streak);
  if (tier === 0) {
    return <>{props.children}</>;
  }
  return (
    <span className="streak-name" data-tier={tier}>
      {props.children}
      <span className="visually-hidden">, {streakLabel(props.streak)}</span>
    </span>
  );
}
