import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import type { BaselineBandPoint, SkillBoardRow } from "../../src/api/types";
import { boardSlice, funnelGeometry } from "../../src/board/core";

const TODAY = "2026-08-14";

function row(over: Partial<SkillBoardRow> & { n: number }): SkillBoardRow {
  return {
    player: `p-${over.n}`,
    display_name: "A Player",
    eligible: over.n >= 30,
    theta: 1,
    shrunk: null,
    y: 0,
    v: 1 / over.n,
    expected_rank: null,
    rank_low: null,
    rank_high: null,
    evidence_p: 0.5,
    log_e_value: 0,
    anytime_significance: 1,
    ...over,
  };
}

describe("the funnel geometry", () => {
  it("spaces the trial count on a logarithmic axis", () => {
    // The assertion that fails loudly if anyone "simplifies" the
    // axis to linear. 3, 30 and 300 are a geometric run, so they
    // must land at equal distances; on a linear axis 3 and 30
    // would both be crushed against the left edge.
    const geometry = funnelGeometry(
      [row({ n: 3 }), row({ n: 30 }), row({ n: 300 })],
      [],
      "nobody",
    );
    const xs = geometry.points.map((point) => point.x);
    expect(xs[0]).toBeCloseTo(0, 10);
    expect(xs[1]).toBeCloseTo(0.5, 10);
    expect(xs[2]).toBeCloseTo(1, 10);
  });

  it("puts a high skill number near the top", () => {
    // SVG y runs down, so the better player is the smaller y.
    const geometry = funnelGeometry(
      [row({ n: 50, y: -0.4 }), row({ n: 50, y: 0.4 })],
      [],
      "nobody",
    );
    const [low, high] = geometry.points;
    if (low === undefined || high === undefined) {
      throw new Error("two points");
    }
    expect(high.y).toBeLessThan(low.y);
  });

  it("keeps every point and every band edge inside the box", () => {
    const rows = [row({ n: 3, y: 1.4 }), row({ n: 400, y: -0.2 })];
    const band: BaselineBandPoint[] = [
      { n: 3, low: -1.1, high: 1.2 },
      { n: 400, low: -0.04, high: 0.16 },
    ];
    const geometry = funnelGeometry(rows, band, "nobody");
    for (const point of [...geometry.points]) {
      expect(point.x).toBeGreaterThanOrEqual(0);
      expect(point.x).toBeLessThanOrEqual(1);
      expect(point.y).toBeGreaterThanOrEqual(0);
      expect(point.y).toBeLessThanOrEqual(1);
    }
    for (const edge of geometry.band) {
      expect(edge.top).toBeGreaterThanOrEqual(0);
      expect(edge.bottom).toBeLessThanOrEqual(1);
      // top is the high skill number, thus the smaller fraction.
      expect(edge.top).toBeLessThan(edge.bottom);
    }
  });

  it("narrows the band as the trial count rises", () => {
    const band: BaselineBandPoint[] = [
      { n: 3, low: -1.1, high: 1.2 },
      { n: 30, low: -0.3, high: 0.42 },
      { n: 400, low: -0.04, high: 0.16 },
    ];
    const geometry = funnelGeometry(
      [row({ n: 3 }), row({ n: 400 })],
      band,
      "x",
    );
    const widths = geometry.band.map((edge) => edge.bottom - edge.top);
    expect(widths).toEqual([...widths].sort((a, b) => b - a));
  });

  it("marks the caller by store key and not by label", () => {
    // Two players may share a display name; the store key is
    // unique. A chart that highlights on the label lights up
    // strangers.
    const rows = [
      row({ n: 40, player: "ade", display_name: "Quiet Signal" }),
      row({ n: 40, player: "bru", display_name: "Quiet Signal" }),
    ];
    const geometry = funnelGeometry(rows, [], "ade");
    expect(geometry.points.filter((point) => point.self)).toHaveLength(1);
    expect(geometry.points.find((point) => point.self)?.player).toBe("ade");
  });

  it("reports an empty board rather than dividing by nothing", () => {
    const geometry = funnelGeometry([], [], "ade");
    expect(geometry.empty).toBe(true);
    expect(geometry.points).toEqual([]);
  });

  it("centres a single point instead of dividing by a flat range", () => {
    const geometry = funnelGeometry([row({ n: 40, y: 0.2 })], [], "ade");
    const point = geometry.points[0];
    expect(point?.x).toBe(0.5);
    expect(Number.isFinite(point?.y)).toBe(true);
  });

  it("labels the axes with skill numbers, never log values", () => {
    // A player never meets a log value: only the spacing is
    // logarithmic. 1.000 is chance and must be drawable.
    const rows = [row({ n: 5, y: -0.5 }), row({ n: 300, y: 0.5 })];
    const geometry = funnelGeometry(rows, [], "ade");
    expect(geometry.skillTicks.map((tick) => tick.value)).toContain(1);
    for (const tick of geometry.skillTicks) {
      expect(tick.value).toBeGreaterThan(0);
      expect(tick.position).toBeGreaterThanOrEqual(0);
      expect(tick.position).toBeLessThanOrEqual(1);
    }
    // The domain is [5, 300]: 3 falls outside it and 1000 does too.
    expect(geometry.trialTicks.map((tick) => tick.value)).toEqual([
      10, 30, 100, 300,
    ]);
  });

  it("draws the real mock population without leaving the box", async () => {
    const board = await makeMockApi({ today: TODAY }).getSkillLeaderboard();
    const geometry = funnelGeometry(board.rows, board.baseline_band, "ade");
    expect(geometry.points).toHaveLength(board.rows.length);
    expect(geometry.points.some((point) => !point.eligible)).toBe(true);
    for (const point of geometry.points) {
      expect(point.x).toBeGreaterThanOrEqual(0);
      expect(point.x).toBeLessThanOrEqual(1);
      expect(point.y).toBeGreaterThanOrEqual(0);
      expect(point.y).toBeLessThanOrEqual(1);
    }
  });
});

describe("the ranked slice", () => {
  it("ranks the eligible alone and leaves the rest to the chart", async () => {
    const board = await makeMockApi({ today: TODAY }).getSkillLeaderboard();
    const slice = boardSlice(board.rows, "ade", 25);
    expect(slice.total).toBe(board.eligible_count);
    expect(slice.shown).toHaveLength(25);
    for (const shown of slice.shown) {
      expect(shown.eligible).toBe(true);
    }
  });

  it("pins the caller below the cut and never twice", () => {
    const rows = Array.from({ length: 40 }, (_, index) =>
      row({ n: 50, player: `p${index}`, expected_rank: index + 1 }),
    );
    const outside = boardSlice(rows, "p30", 25);
    expect(outside.pinned?.player).toBe("p30");
    expect(outside.shown.map((shown) => shown.player)).not.toContain("p30");

    const inside = boardSlice(rows, "p3", 25);
    expect(inside.pinned).toBeNull();
    expect(inside.shown.map((shown) => shown.player)).toContain("p3");
  });

  it("pins nothing for a caller who is not ranked", () => {
    // A player below the floor is on the chart, not in the table,
    // and the screen says where they stand in its own words.
    const rows = [row({ n: 40, player: "ade" }), row({ n: 4, player: "new" })];
    const slice = boardSlice(rows, "new", 25);
    expect(slice.pinned).toBeNull();
    expect(slice.total).toBe(1);
  });
});
