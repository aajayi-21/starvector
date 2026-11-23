/**
 * The order of a day's board and its first three, for the podium of the
 * leaderboard (screens/leaderboard-day.tsx), and the sketch of each
 * player from the sends of the day (spec SS1 §7). Pure functions over
 * the wire.
 *
 * The podium is the owner's design of 2026-11-22. It sets the first
 * three apart and adds no number: each one keeps the result, the
 * place of the photo, and the order that the board gives it.
 */

import type { LeaderboardRow, SendEntry, SendsPage } from "../api/types";

/** A row of the day's board with its order on the board. */
export interface PlacedRow {
  row: LeaderboardRow;
  /**
   * The order among the rows that each player sees, from 1. Null for
   * the caller's own row below the floor of spec A2 §9.5: no other
   * player sees that row, so it holds no order.
   */
  order: number | null;
  /** True when one more row that each player sees has the same order. */
  tied: boolean;
}

/** How many rows the podium holds. */
export const PODIUM_SIZE = 3;

/**
 * The order of each row, in the sequence of the wire. The server sends
 * the rows sorted by the result, the best first (service/rollup.py),
 * and this keeps that sequence. An equal result shares the smaller
 * order, as the server ranks: two rows at 1 and the next at 3.
 */
export function placeRows(rows: ReadonlyArray<LeaderboardRow>): PlacedRow[] {
  const orders: Array<number | null> = [];
  let seen = 0;
  let last: { p: number; order: number } | null = null;
  for (const row of rows) {
    if (!row.public) {
      orders.push(null);
      continue;
    }
    seen += 1;
    const order: number = last !== null && row.p === last.p ? last.order : seen;
    orders.push(order);
    last = { p: row.p, order };
  }
  return rows.map((row, index) => {
    const order = orders[index] ?? null;
    const shared =
      order !== null && orders.filter((other) => other === order).length > 1;
    return { row, order, tied: shared };
  });
}

/**
 * The podium: the first rows that each player sees, at most three. A
 * tie at the third place leaves the other tied rows in the table, with
 * the same order.
 */
export function podiumRows(placed: ReadonlyArray<PlacedRow>): PlacedRow[] {
  return placed.filter((one) => one.order !== null).slice(0, PODIUM_SIZE);
}

/** The send of each player of the day, by the board label. */
export function sendsByPlayer(
  pages: ReadonlyArray<SendsPage>,
): Map<string, SendEntry> {
  const found = new Map<string, SendEntry>();
  for (const page of pages) {
    for (const entry of page.entries) {
      found.set(entry.player, entry);
    }
  }
  return found;
}
