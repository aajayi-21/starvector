/**
 * The mirror of the two Layer 0 gates a screen can check by itself
 * (spec PL1 §8). The ink gate needs the server's render, so its refusal
 * stays the server's. The floor comes from the server: it is a value of
 * the scoring config, and a screen holds no copy of it.
 */

export type SendBlock = "empty" | "too-few-strokes" | null;

export function sendBlock(
  strokes: number,
  hasWords: boolean,
  minStrokes: number,
): SendBlock {
  if (strokes > 0 && strokes < minStrokes) {
    return "too-few-strokes";
  }
  return strokes === 0 && !hasWords ? "empty" : null;
}

export function sendBlockHint(block: SendBlock, minStrokes: number): string {
  switch (block) {
    case "too-few-strokes":
      return `A sketch needs at least ${minStrokes} strokes. Add another, or clear it and use words only.`;
    case "empty":
      return "Draw something or add a word first.";
    case null:
      return "";
  }
}
