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
 * The public page of one instant trial (spec IM1 §10) is open to each
 * browser too. Its path holds the trial, so it is a prefix and not one
 * of the fixed paths.
 */
export const TRIAL_PATH_PREFIX = "/t/";

/** True for a path that a browser with no session can open. */
export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.has(pathname) || pathname.startsWith(TRIAL_PATH_PREFIX);
}

/**
 * The screens with no footer (spec F1 §2): the two drawing screens,
 * where the canvas takes the window height and a phone pins the send
 * bar above the tab bar.
 */
export const NO_FOOTER_PATHS: ReadonlySet<string> = new Set([
  "/today",
  "/instant",
]);

/**
 * The screens that reach the edges of the window: the home screen and
 * Your results each stand on a sky. The page gives such a screen no
 * side margin and no space over it, and the screen sets its own.
 */
export const BLEED_PATHS: ReadonlySet<string> = new Set(["/", "/history"]);
