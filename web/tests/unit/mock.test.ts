import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";

const TODAY = "2026-08-14";

function shiftDay(day: string, byDays: number): string {
  const epoch = Date.parse(`${day}T00:00:00Z`);
  return new Date(epoch + byDays * 86_400_000).toISOString().slice(0, 10);
}

describe("mock determinism", () => {
  it("answers byte-identically across instances", async () => {
    const one = makeMockApi({ today: TODAY });
    const two = makeMockApi({ today: TODAY });
    for (const pick of [
      (api: ReturnType<typeof makeMockApi>) => api.getHistory(),
      (api: ReturnType<typeof makeMockApi>) => api.getMe(),
      (api: ReturnType<typeof makeMockApi>) => api.getPracticeDays(),
      (api: ReturnType<typeof makeMockApi>) => api.getReveal(),
    ]) {
      expect(JSON.stringify(await pick(one))).toBe(
        JSON.stringify(await pick(two)),
      );
    }
  });

  it("differs across anchor days", async () => {
    const one = await makeMockApi({ today: TODAY }).getHistory();
    const two = await makeMockApi({ today: "2026-09-14" }).getHistory();
    expect(JSON.stringify(one)).not.toBe(JSON.stringify(two));
  });
});

describe("history and streak", () => {
  it("keeps p, beaten, and rank consistent with each other", async () => {
    const history = await makeMockApi({ today: TODAY }).getHistory();
    expect(history.days.length).toBeGreaterThan(0);
    for (const row of history.days) {
      expect(row.p).toBeGreaterThan(0);
      expect(row.p).toBeLessThan(1);
      const beaten = Math.round(row.p * row.decoy_count);
      expect(row.target_rank).toBe(row.decoy_count - beaten + 1);
    }
  });

  it("computes the streak per the section 7 definition", async () => {
    const api = makeMockApi({ today: TODAY });
    const history = await api.getHistory();
    const me = await api.getMe();
    const played = new Set(history.days.map((row) => row.day));
    const newest = history.days[0]?.day;
    expect(newest).toBeDefined();
    let expected = 0;
    let cursor = newest as string;
    while (played.has(cursor)) {
      expected += 1;
      cursor = shiftDay(cursor, -1);
    }
    expect(me.streak).toBe(expected);
  });
});

describe("leaderboard", () => {
  it("sorts by p descending and reuses the own-row history p", async () => {
    const api = makeMockApi({ today: TODAY });
    const history = await api.getHistory();
    const day = history.days[0]?.day as string;
    const board = await api.getLeaderboard(day);
    const ps = board.rows.map((row) => row.p);
    expect([...ps].sort((a, b) => b - a)).toEqual(ps);
    const own = board.rows.find((row) => row.player === "ade");
    expect(own?.p).toBe(history.days[0]?.p);
  });

  it("refuses a day that is not revealed", async () => {
    const api = makeMockApi({ today: TODAY });
    await expect(api.getLeaderboard("1999-01-01")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("the full-mock day flow", () => {
  const record = {
    impressions: ["tall vertical structure"],
    canvas_strokes: [],
    groups: [],
    relations: [],
    pasted_text: null,
  };

  it("locks after one send with the already-submitted cause", async () => {
    const api = makeMockApi({ today: TODAY });
    const ack = await api.submit(record);
    expect(ack.trial_id).toMatch(/^[0-9a-f]{32}$/);
    expect(ack.atom_count).toBe(1);
    const again = api.submit(record);
    await expect(again).rejects.toMatchObject({
      status: 409,
      refusalCause: "already-submitted",
    });
  });

  it("scores practice deterministically by day and record", async () => {
    const api = makeMockApi({ today: TODAY });
    const days = await api.getPracticeDays();
    const day = days.days[0]?.day as string;
    const one = await api.scorePractice(day, record);
    const two = await api.scorePractice(day, record);
    expect(JSON.stringify(one)).toBe(JSON.stringify(two));
    const other = await api.scorePractice(day, {
      ...record,
      impressions: ["cold"],
    });
    expect(JSON.stringify(other)).not.toBe(JSON.stringify(one));
    expect(one.ranking_head).toHaveLength(10);
    const targets = one.ranking_head.filter((row) => row.is_target);
    expect(targets.length).toBeLessThanOrEqual(1);
  });

  it("serves a deterministic stored submission for played days", async () => {
    const api = makeMockApi({ today: TODAY });
    const history = await api.getHistory();
    const day = history.days[0]?.day as string;
    const one = await api.getSubmission(day);
    const two = await api.getSubmission(day);
    expect(JSON.stringify(one)).toBe(JSON.stringify(two));
    for (const stroke of one.record.canvas_strokes) {
      expect(stroke).toHaveProperty("group_id");
      for (const point of stroke.points) {
        expect(point[0]).toBeGreaterThanOrEqual(0);
        expect(point[0]).toBeLessThanOrEqual(1);
      }
    }
    await expect(api.getSubmission("1999-01-01")).rejects.toMatchObject({
      status: 404,
    });
  });
});
