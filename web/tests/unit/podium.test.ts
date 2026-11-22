import { describe, expect, it } from "vitest";

import type { LeaderboardRow, SendsPage } from "../../src/api/types";
import { placeRows, podiumRows, sendsByPlayer } from "../../src/board/podium";

function row(player: string, p: number, open = true): LeaderboardRow {
  return {
    player,
    display_name: player,
    avatar_hash: null,
    p,
    target_rank: 1,
    decoy_count: 119,
    streak: 0,
    public: open,
  };
}

describe("the order of the day's board", () => {
  it("shares the smaller order on an equal result, as the server ranks", () => {
    const placed = placeRows([
      row("a", 0.9),
      row("b", 0.8),
      row("c", 0.8),
      row("d", 0.7),
    ]);
    expect(placed.map((one) => one.order)).toEqual([1, 2, 2, 4]);
    expect(placed.map((one) => one.tied)).toEqual([false, true, true, false]);
  });

  it("gives the caller's own row below the floor no order", () => {
    // Spec A2 §9.5: no other player sees that row, so the rows after it
    // keep the order that each other player sees.
    const placed = placeRows([
      row("ade", 0.95, false),
      row("a", 0.9),
      row("b", 0.8),
    ]);
    expect(placed.map((one) => one.order)).toEqual([null, 1, 2]);
    expect(podiumRows(placed).map((one) => one.row.player)).toEqual(["a", "b"]);
  });

  it("puts three rows on the podium and leaves a tie at third in the table", () => {
    const placed = placeRows([
      row("a", 0.9),
      row("b", 0.8),
      row("c", 0.7),
      row("d", 0.7),
    ]);
    const podium = podiumRows(placed);
    expect(podium.map((one) => one.row.player)).toEqual(["a", "b", "c"]);
    expect(podium[2]?.tied).toBe(true);
    const rest = placed.filter((one) => !podium.includes(one));
    expect(rest.map((one) => [one.row.player, one.order])).toEqual([["d", 3]]);
  });

  it("holds fewer places on a day with fewer players", () => {
    expect(podiumRows(placeRows([row("a", 0.4)]))).toHaveLength(1);
    expect(podiumRows(placeRows([]))).toEqual([]);
  });
});

describe("the sends of the day by player", () => {
  it("finds a send on any page", () => {
    const page = (players: string[]): SendsPage => ({
      day: "2026-11-19",
      total: 3,
      next_before: null,
      entries: players.map((player) => ({
        player,
        named: true,
        avatar_hash: null,
        state: "sketch",
        strokes: [],
      })),
    });
    const found = sendsByPlayer([page(["a", "b"]), page(["c"])]);
    expect([...found.keys()]).toEqual(["a", "b", "c"]);
  });
});
