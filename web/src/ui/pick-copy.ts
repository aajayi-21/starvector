/**
 * The words that say when the day's photo is picked (spec VP1 §8).
 *
 * Under the pick after the close no photo exists during play, so a
 * screen must not say one is hidden. A commit-v1 day keeps the earlier
 * words, which are true for it. One place holds each pair, so the two
 * protocols cannot drift apart screen by screen.
 */

import type { PickProtocol } from "../api/types";

export function isPostClose(protocol: PickProtocol | undefined): boolean {
  return protocol === "vp1";
}

/** "the photo" under vp1, "the hidden photo" before it. */
export function photoNoun(protocol: PickProtocol | undefined): string {
  return isPostClose(protocol) ? "the day's photo" : "the hidden photo";
}
