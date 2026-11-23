/**
 * The addresses the site footer points at (spec F1 §2). One place to
 * edit: the footer, the About page, and the tests read these.
 */

/** The public source repository. */
export const GITHUB_URL = "https://github.com/aajayi-21/starvector";

/**
 * The paths a signed-out browser can open (spec F1 §3). Each holds
 * fixed text alone: no day, no result, no player.
 */
export const PUBLIC_PATHS: ReadonlySet<string> = new Set([
  "/about",
  "/releases",
]);

/**
 * The screens with no footer (spec F1 §2): the two drawing screens,
 * where the canvas takes the window height and a phone pins the send
 * bar above the tab bar.
 */
export const NO_FOOTER_PATHS: ReadonlySet<string> = new Set([
  "/today",
  "/practice",
]);

/**
 * The screens that reach the edges of the window: the home screen and
 * Your results each stand on a sky. The page gives such a screen no
 * side margin and no space over it, and the screen sets its own.
 */
export const BLEED_PATHS: ReadonlySet<string> = new Set(["/", "/history"]);
