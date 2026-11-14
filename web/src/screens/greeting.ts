/**
 * The home heading's words (spec H1 §5). Pure functions: the screen
 * hands in the clock hour and a random generator, so a test can pin
 * both.
 */

export type Random = () => number;

function timeOfDay(hour: number): string {
  if (hour < 5) {
    return "Good evening";
  }
  if (hour < 12) {
    return "Good morning";
  }
  return hour < 18 ? "Good afternoon" : "Good evening";
}

/** The set one visit draws from: the clock greeting and two others. */
export function greetingVariants(hour: number): string[] {
  return [timeOfDay(hour), "Welcome back", "Ready to view"];
}

export function pickGreeting(hour: number, random: Random): string {
  const variants = greetingVariants(hour);
  return variants[Math.floor(random() * variants.length)] ?? variants[0] ?? "";
}

/**
 * The index of the next epigraph: random, and never the one on
 * screen. `count` is at least 2 for a change to exist.
 */
export function nextIndex(current: number, count: number, random: Random) {
  if (count < 2) {
    return current;
  }
  const step = 1 + Math.floor(random() * (count - 1));
  return (current + step) % count;
}
