import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";

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
      (api: ReturnType<typeof makeMockApi>) => api.getLeaderboard(TODAY),
      (api: ReturnType<typeof makeMockApi>) => api.getSkillLeaderboard(),
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
  it("keeps the record's p = beaten / decoy_count identity", async () => {
    const history = await makeMockApi({ today: TODAY }).getHistory();
    expect(history.days.length).toBeGreaterThan(0);
    for (const row of history.days) {
      expect(row.p).toBeGreaterThan(0);
      expect(row.p).toBeLessThan(1);
      // core/ranking.py: p = (beaten + 0.5 * tied) / decoy_count.
      const beaten = row.p * row.decoy_count;
      expect(Number.isInteger(beaten)).toBe(true);
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

  it("serves any named day deterministically", async () => {
    // In composite mode the caller holds a day the live server
    // revealed; the mock cannot know that set, thus a named day is
    // always served (the true revealed-only 404 is the backend
    // phase's).
    const api = makeMockApi({ today: TODAY });
    const one = await api.getLeaderboard("1999-01-01");
    const two = await api.getLeaderboard("1999-01-01");
    expect(JSON.stringify(one)).toBe(JSON.stringify(two));
    const reveal = await api.getReveal("1999-01-01");
    expect(reveal.day).toBe("1999-01-01");
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

describe("the mock skill board", () => {
  it("keeps the shapes spec M1 section 6 states", async () => {
    const board = await makeMockApi({ today: TODAY }).getSkillLeaderboard();
    expect(board.rows.length).toBeGreaterThan(30);
    expect(board.variation?.dof).toBe(board.eligible_count - 1);
    expect(board.eligible_count).toBe(
      board.rows.filter((row) => row.n >= board.eligibility_floor).length,
    );
    for (const row of board.rows) {
      expect(row.theta).toBeGreaterThan(0);
      // The two evidence fields must agree: a screen renders one
      // from the other (ruling 15 of 2026-08-16).
      expect(Math.exp(-row.log_e_value)).toBeCloseTo(
        row.anytime_significance,
        3,
      );
    }
  });

  it("ranks the eligible and leaves the rest without a rank", () => {
    // Ruling 17 of 2026-08-16. The ranking fields are null below
    // the floor because ranking those players would move everybody
    // else's rank - not because the number is unknown.
    return makeMockApi({ today: TODAY })
      .getSkillLeaderboard()
      .then((board) => {
        const ranked = board.rows.filter((row) => row.eligible);
        const rest = board.rows.filter((row) => !row.eligible);
        expect(ranked.length).toBe(board.eligible_count);
        expect(rest.length).toBeGreaterThan(0);
        // The eligible run leads, ordered by the expected rank.
        expect(board.rows.slice(0, ranked.length)).toEqual(ranked);
        for (const row of ranked) {
          expect(row.n).toBeGreaterThanOrEqual(board.eligibility_floor);
          expect(row.shrunk).not.toBeNull();
          expect(row.rank_low).toBeLessThanOrEqual(row.expected_rank ?? 0);
          expect(row.rank_high).toBeGreaterThanOrEqual(row.expected_rank ?? 0);
        }
        for (const row of rest) {
          expect(row.n).toBeLessThan(board.eligibility_floor);
          expect(row.shrunk).toBeNull();
          expect(row.expected_rank).toBeNull();
          expect(row.rank_low).toBeNull();
          expect(row.rank_high).toBeNull();
          // The chart still plots them, thus these two travel.
          expect(row.y).toBeTypeOf("number");
          expect(row.v).toBeGreaterThan(0);
        }
      });
  });

  it("pulls a low-trial player toward the middle", async () => {
    // The property the posterior expected rank buys: a lucky short
    // run cannot take the top, and no threshold does the work.
    const board = await makeMockApi({ today: TODAY }).getSkillLeaderboard();
    const ranked = board.rows.filter((row) => row.eligible);
    const middle = (ranked.length + 1) / 2;
    const bySkill = [...ranked].sort((a, b) => b.y - a.y);
    const byTrials = [...ranked].sort((a, b) => a.n - b.n);
    const lowest = byTrials[0];
    const highest = byTrials[byTrials.length - 1];
    if (lowest === undefined || highest === undefined) {
      throw new Error("the board must hold eligible players");
    }
    const rawPosition = bySkill.indexOf(lowest) + 1;
    expect(Math.abs((lowest.expected_rank ?? 0) - middle)).toBeLessThan(
      Math.abs(rawPosition - middle),
    );
    expect((lowest.rank_high ?? 0) - (lowest.rank_low ?? 0)).toBeGreaterThan(
      (highest.rank_high ?? 0) - (highest.rank_low ?? 0),
    );
  });

  it("generates players who share a display name", async () => {
    // 140 players across a 64-name space: the shared-label case is
    // exercised without being planted, and the store keys stay
    // unique. A screen that keys on the label breaks here.
    const board = await makeMockApi({ today: TODAY }).getSkillLeaderboard();
    const keys = new Set(board.rows.map((row) => row.player));
    const labels = new Set(board.rows.map((row) => row.display_name));
    expect(keys.size).toBe(board.rows.length);
    expect(labels.size).toBeLessThan(board.rows.length);
  });
});
