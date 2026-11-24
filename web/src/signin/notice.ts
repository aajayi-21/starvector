/**
 * The notice that results are public (spec R1 §3.1): the one place
 * that holds its text and its version number. The sign-up card, the
 * blocking notice screen, and the mock read it from here.
 *
 * Version 2 is the text of spec SS1 §10: other players see a sketch
 * after their own send, and each player has a public page. Version 3
 * is the text of spec IM1 §14: an instant trial is public when its
 * result comes.
 *
 * A change of the text is a new version number (spec R1 §3.2), and
 * the server holds the same number: a server-side test reads the
 * `NOTICE_VERSION` line of this file, thus that line keeps its shape.
 */

export const NOTICE_VERSION = 3;

/** The first sentence, which the screens show in bold. */
export const NOTICE_LEAD = "Your sketches and results are public.";

/** The remaining sentences of the notice. */
export const NOTICE_BODY =
  "An instant trial is public when its result comes: each person with its address can see your sketch, your score and your name. After you send to a daily challenge, each player who sent that day can see your sketch. After each day closes, each person can see your username, score and sketches on your public page, and your words in an open database. Do not sketch or type anything private.";
