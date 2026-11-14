/**
 * The notice that results are public (spec R1 §3.1): the one place
 * that holds its text and its version number. The sign-up card, the
 * blocking notice screen, and the mock read it from here.
 *
 * A change of the text is a new version number (spec R1 §3.2), and
 * the server holds the same number: a server-side test reads the
 * `NOTICE_VERSION` line of this file, thus that line keeps its shape.
 */

export const NOTICE_VERSION = 1;

/** The first sentence, which the screens show in bold. */
export const NOTICE_LEAD = "Your results are public.";

/** The remaining sentences of the notice. */
export const NOTICE_BODY =
  "Your username, score, words and sketches are published in an open database after each day closes. Do not type anything private.";
