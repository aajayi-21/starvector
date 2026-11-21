/**
 * The share card of one result: the words and the numbers that the
 * image shows. Pure functions of the result, with no canvas and no
 * browser object, so a unit test reads each line.
 *
 * The card states the result against chance and grades nothing, by the
 * copy rule of spec M1 §9: no "good match" wording. It holds what the
 * player sees on the results screen and nothing more: the day, the
 * code, the share of the other photos beaten, and the place of the
 * hidden photo. The hidden photo itself is not on the card: each one
 * has its own author and license.
 */

import { ordinal, percentBeaten } from "../ui/format";

export const CARD_WIDTH = 1080;
export const CARD_HEIGHT = 1350;

export interface ShareResult {
  /** The day label: the identifier, and the date in the file name. */
  day: string;
  /** The name of the day in the player's own zone (ui/day-names.ts). */
  dateLine: string;
  /** The day's code, when the caller has it. */
  trialCode: string | null;
  p: number;
  targetRank: number;
  decoyCount: number;
  /** The player's username, when the caller has it. */
  player: string | null;
  /** The site's host, for the last line of the card. */
  host: string;
}

export interface ShareCard {
  fileName: string;
  dateLine: string;
  codeLine: string | null;
  percent: number;
  percentText: string;
  captionLine: string;
  placeLead: string;
  placeValue: string;
  placeTail: string;
  chanceLabel: string;
  byLine: string | null;
  siteLine: string;
  /** The words that go with the image when the device shares it. */
  shareText: string;
  /** What the image shows, for a reader who cannot see it. */
  altText: string;
}

const COUNT_FORMAT = new Intl.NumberFormat("en-US");

/** The card of one result. */
export function shareCard(result: ShareResult): ShareCard {
  const percent = percentBeaten(result.p);
  const total = result.decoyCount + 1;
  const place = ordinal(result.targetRank);
  const dateLine = result.dateLine;
  const totalText = COUNT_FORMAT.format(total);
  const sentence =
    `I beat ${percent}% of the photos on Starvector, ${dateLine}. ` +
    "Guessing averages 50%.";
  return {
    fileName: `starvector-${result.day}.png`,
    dateLine,
    codeLine: result.trialCode === null ? null : `Code ${result.trialCode}`,
    percent,
    percentText: `${percent}%`,
    captionLine: "of the other photos beaten",
    placeLead: "The hidden photo was my",
    placeValue: place,
    placeTail: `closest match of ${totalText}`,
    chanceLabel: "50% · guessing",
    byLine: result.player,
    siteLine: result.host,
    shareText: sentence,
    altText:
      `Starvector result for ${dateLine}: ${percent}% of the other ` +
      `photos beaten. The hidden photo was the ${place}-closest match ` +
      `of ${totalText}. Guessing averages 50%.`,
  };
}

// ── The card of a sketch, before the reveal (spec SS1 §6) ────────

export interface SketchShare {
  /** The day label: the date in the file name. */
  day: string;
  /** The name of the day in the player's own zone (ui/day-names.ts). */
  dateLine: string;
  /** The player's username, when the caller has it. */
  player: string | null;
  /** The site's host, for the last line of the card. */
  host: string;
  /** True when the photo is picked after the day closes (spec VP1). */
  postClose: boolean;
}

/**
 * The words of the image that a player shares after the send. The type
 * has no slot for a score, a code, a word of the send, or a target: no
 * result is there before the reveal, and a second person gets the
 * sketch alone.
 */
export interface SketchCard {
  fileName: string;
  dateLine: string;
  /** One sentence that says when the photo comes. */
  noteLine: string;
  byLine: string | null;
  siteLine: string;
  /** The words that go with the image when the device shares it. */
  shareText: string;
  /** What the image shows, for a reader who cannot see it. */
  altText: string;
}

/** The card of one sketch, with no result in it. */
export function sketchCard(share: SketchShare): SketchCard {
  const noteLine = share.postClose
    ? "The photo is picked after the day closes."
    : "The photo is revealed when the day closes.";
  const by = share.player === null ? "" : ` by ${share.player}`;
  return {
    fileName: `starvector-sketch-${share.day}.jpg`,
    dateLine: share.dateLine,
    noteLine,
    byLine: share.player,
    siteLine: share.host,
    shareText: `My sketch for Starvector, ${share.dateLine}. ${noteLine}`,
    altText: `A sketch${by} for Starvector, ${share.dateLine}. ${noteLine}`,
  };
}
