/**
 * The fixed sketch palette — spec C1 §5 as amended 2026-08-14 and
 * spec W1 §9. Ink sends no wire key and displays as the theme ink;
 * the seven colors share one hex for wire and display.
 */

export interface PaletteEntry {
  readonly name: string;
  /** The wire hex, or null for ink (the key is omitted). */
  readonly wire: string | null;
  readonly display: string;
}

export const PALETTE: readonly PaletteEntry[] = [
  { name: "ink", wire: null, display: "#eceff4" },
  { name: "red", wire: "#bf616a", display: "#bf616a" },
  { name: "orange", wire: "#d08770", display: "#d08770" },
  { name: "yellow", wire: "#ebcb8b", display: "#ebcb8b" },
  { name: "green", wire: "#a3be8c", display: "#a3be8c" },
  { name: "blue", wire: "#81a1c1", display: "#81a1c1" },
  { name: "purple", wire: "#b48ead", display: "#b48ead" },
  { name: "teal", wire: "#8fbcbb", display: "#8fbcbb" },
];

export const INK_INDEX = 0;

/** Group chips and halos cycle the non-ink swatches. */
const GROUP_DISPLAY = PALETTE.slice(1).map((entry) => entry.display);

export function groupDisplay(groupIndex: number): string {
  const wrapped =
    ((groupIndex % GROUP_DISPLAY.length) + GROUP_DISPLAY.length) %
    GROUP_DISPLAY.length;
  return GROUP_DISPLAY[wrapped] ?? "#97a1b4";
}

export function displayOf(colorIndex: number): string {
  return PALETTE[colorIndex]?.display ?? "#eceff4";
}

export function wireOf(colorIndex: number): string | null {
  return PALETTE[colorIndex]?.wire ?? null;
}
