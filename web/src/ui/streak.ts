/**
 * The streak tiers (spec H1 §4). One pure function holds the cut
 * points, so no component names a number of days.
 */

/** The streak in days at which tiers 1, 2, and 3 begin (spec H1 D1). */
export const STREAK_TIER_STARTS = [3, 7, 30] as const;

export type StreakTier = 0 | 1 | 2 | 3;

export function streakTier(streak: number): StreakTier {
  const [first, second, third] = STREAK_TIER_STARTS;
  if (streak >= third) {
    return 3;
  }
  if (streak >= second) {
    return 2;
  }
  return streak >= first ? 1 : 0;
}

/** The words a screen reader gets next to a marked username. */
export function streakLabel(streak: number): string {
  return `${streak}-day streak`;
}
