/**
 * Is the viewport at the narrow layout?
 *
 * The one breakpoint app.css already uses, read once so a drawing
 * can pick its own proportions. An SVG that scales to the column
 * width scales its type with it, so the desktop plot box renders
 * its 11-unit labels at about 6 px on a 390 px screen. Choosing a
 * smaller box at that width keeps the scale factor near 1 and the
 * labels legible.
 *
 * Defaults to false, which is what jsdom's stubbed matchMedia
 * answers, so component tests measure the wide box.
 */

import { useEffect, useState } from "react";

/** Kept equal to the max-width in app.css by hand. */
export const NARROW_QUERY = "(max-width: 720px)";

export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const media = window.matchMedia?.(NARROW_QUERY);
    if (media === undefined) {
      return;
    }
    setNarrow(media.matches);
    const onChange = (event: MediaQueryListEvent): void =>
      setNarrow(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);
  return narrow;
}
