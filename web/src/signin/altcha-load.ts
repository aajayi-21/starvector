/**
 * Loads the ALTCHA widget on demand (spec PW1 §4.2). The sign-up form
 * is the one place that needs it, so the code stays out of the main
 * bundle and a signed-in player never downloads it.
 *
 * The `altcha/external` build has no inline styles and no workers
 * made from blob URLs. Its stylesheet and its PBKDF2 worker are files
 * of this site, so the page's Content-Security-Policy stays as it is:
 * `script-src 'self'` and `worker-src 'self'`.
 */

/** The algorithm the server signs (spec PW1 decision D2). */
export const PROOF_ALGORITHM = "PBKDF2/SHA-256";

let loading: Promise<void> | undefined;

export function loadAltcha(): Promise<void> {
  loading ??= Promise.all([
    import("altcha/external"),
    import("altcha/altcha.css"),
    import("altcha/workers/pbkdf2?worker"),
  ]).then(
    ([, , pbkdf2]) => {
      globalThis.$altcha.algorithms.set(
        PROOF_ALGORITHM,
        () => new pbkdf2.default(),
      );
    },
    (error: unknown) => {
      // A failed download is tried again the next time the form opens.
      loading = undefined;
      throw error;
    },
  );
  return loading;
}
