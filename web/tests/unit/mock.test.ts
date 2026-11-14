import { describe, expect, it } from "vitest";

import { MOCK_PASSWORD, makeMockApi } from "../../src/api/mock";
import {
  allOk,
  isRecoveryCodeShape,
  usernameChecks,
} from "../../src/signin/rules";

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
    const ack = await api.submit(TODAY, record);
    expect(ack.day).toBe(TODAY);
    expect(ack.trial_id).toMatch(/^[0-9a-f]{32}$/);
    expect(ack.atom_count).toBe(1);
    const again = api.submit(TODAY, record);
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

  it("labels each player with the username alone", async () => {
    // Spec A2 ruling 3: the username is the one name. The label on
    // the wire is equal to the key, each key is a legal username,
    // and no two rows share one.
    const board = await makeMockApi({ today: TODAY }).getSkillLeaderboard();
    const keys = new Set(board.rows.map((row) => row.player));
    expect(keys.size).toBe(board.rows.length);
    for (const row of board.rows) {
      expect(row.display_name).toBe(row.player);
      expect(allOk(usernameChecks(row.player))).toBe(true);
    }
  });
});

describe("the mock accounts (spec A2 §8)", () => {
  const GOOD = "four quiet amber lanterns";

  it("says sign-up is open and gives me the two new fields", async () => {
    const api = makeMockApi({ today: TODAY });
    expect(await api.getSignup()).toEqual({ open: true });
    const me = await api.getMe();
    expect(me.has_password).toBe(true);
    expect(me.operator_code).toBeNull();
    expect(me.display_name).toBe(me.player);
  });

  it("makes an account, signs it in, and shows a recovery code", async () => {
    const api = makeMockApi({ today: TODAY });
    const made = await api.signUp("Nova-7", GOOD);
    // Capitals become small letters, and the label is the username.
    expect(made.player).toBe("nova-7");
    expect(made.display_name).toBe("nova-7");
    expect(made.recovery_code).toMatch(/^([A-Z2-9]{4}-){5}[A-Z2-9]{4}$/);
    expect(isRecoveryCodeShape(made.recovery_code)).toBe(true);
    const me = await api.getMe();
    expect(me.player).toBe("nova-7");
    expect(me.has_password).toBe(true);
  });

  it("refuses a sign-up with the server's causes and statuses", async () => {
    const api = makeMockApi({ today: TODAY });
    const cases: Array<[string, string, number, string]> = [
      ["ab", GOOD, 400, "name-rule"],
      ["9lives", GOOD, 400, "name-rule"],
      ["two--hyphens", GOOD, 400, "name-rule"],
      ["ends-", GOOD, 400, "name-rule"],
      ["r00t", GOOD, 400, "name-reserved"],
      ["nova", "too short", 400, "password-rule"],
      ["nova", "the nova is my name", 400, "password-rule"],
      ["nova", "PasswordPassword", 400, "password-usual"],
      // The folded shape of a claimed name: a-d-e is ade.
      ["a-d-e", GOOD, 409, "name-taken"],
    ];
    for (const [username, password, status, cause] of cases) {
      await expect(api.signUp(username, password)).rejects.toMatchObject({
        status,
        refusalCause: cause,
      });
    }
  });

  it("gives one answer for each pair that does not sign in", async () => {
    const api = makeMockApi({ today: TODAY });
    for (const [username, password] of [
      ["ade", "not the password"],
      ["nobody-here", MOCK_PASSWORD],
    ] as const) {
      await expect(api.signIn(username, password)).rejects.toMatchObject({
        status: 401,
        refusalCause: "sign-in",
      });
    }
    expect(await api.signIn("ADE", MOCK_PASSWORD)).toEqual({
      player: "ade",
      display_name: "ade",
    });
  });

  it("answers 401 on me after a sign-out, until a sign-in", async () => {
    const api = makeMockApi({ today: TODAY });
    await api.signOut();
    await expect(api.getMe()).rejects.toMatchObject({ status: 401 });
    await api.signIn("ade", MOCK_PASSWORD);
    expect((await api.getMe()).player).toBe("ade");
    // This device is in the device table again.
    const sessions = await api.getSessions();
    expect(sessions.sessions.filter((row) => row.current)).toHaveLength(1);
  });

  it("starts signed out when asked", async () => {
    const api = makeMockApi({ today: TODAY, signedIn: false });
    await expect(api.getMe()).rejects.toMatchObject({ status: 401 });
  });

  it("recovers with the code one time and gives a new code", async () => {
    const api = makeMockApi({ today: TODAY });
    const made = await api.signUp("nova", GOOD);
    await api.signOut();
    const next = "five slow north harbors";
    // The new password is checked first and says nothing of the account.
    await expect(
      api.recover("nova", made.recovery_code, "short"),
    ).rejects.toMatchObject({ status: 400, refusalCause: "password-rule" });
    await expect(
      api.recover("nova", "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2", next),
    ).rejects.toMatchObject({ status: 401, refusalCause: "recovery" });
    // Small letters and spaces in place of hyphens do not count.
    const typed = made.recovery_code.toLowerCase().replaceAll("-", " ");
    const back = await api.recover("nova", typed, next);
    expect(back.player).toBe("nova");
    expect(back.recovery_code).not.toBe(made.recovery_code);
    // The used code is dead, and the earlier password with it.
    await api.signOut();
    await expect(
      api.recover("nova", made.recovery_code, next),
    ).rejects.toMatchObject({ status: 401, refusalCause: "recovery" });
    await expect(api.signIn("nova", GOOD)).rejects.toMatchObject({
      status: 401,
    });
    expect((await api.signIn("nova", next)).player).toBe("nova");
  });

  it("changes the password and signs the other devices out", async () => {
    const api = makeMockApi({ today: TODAY });
    await expect(api.setPassword(GOOD, "not it")).rejects.toMatchObject({
      status: 403,
      refusalCause: "password",
    });
    await expect(api.setPassword("short", MOCK_PASSWORD)).rejects.toMatchObject(
      { status: 400, refusalCause: "password-rule" },
    );
    const answer = await api.setPassword(GOOD, MOCK_PASSWORD);
    // A change gives no recovery code: the code does not move.
    expect(answer).toEqual({
      changed: true,
      signed_out: 1,
      recovery_code: null,
    });
    expect((await api.getSessions()).sessions).toHaveLength(1);
  });

  it("sets a first password with no current one, with a first code", async () => {
    const api = makeMockApi({ today: TODAY, hasPassword: false });
    expect((await api.getMe()).has_password).toBe(false);
    // No password yet: a recovery code has nothing to check against.
    await expect(api.newRecoveryCode("anything")).rejects.toMatchObject({
      status: 403,
      refusalCause: "password",
    });
    const answer = await api.setPassword(GOOD);
    expect(answer.changed).toBe(true);
    expect(isRecoveryCodeShape(answer.recovery_code ?? "")).toBe(true);
    expect((await api.getMe()).has_password).toBe(true);
  });

  it("makes a new recovery code for the current password", async () => {
    const api = makeMockApi({ today: TODAY });
    await expect(api.newRecoveryCode("not it")).rejects.toMatchObject({
      status: 403,
      refusalCause: "password",
    });
    const one = await api.newRecoveryCode(MOCK_PASSWORD);
    const two = await api.newRecoveryCode(MOCK_PASSWORD);
    expect(isRecoveryCodeShape(one.recovery_code)).toBe(true);
    expect(two.recovery_code).not.toBe(one.recovery_code);
  });

  it("stops an operator's code, with one answer with and without one", async () => {
    const api = makeMockApi({
      today: TODAY,
      operatorCode: {
        issued_at: "2026-08-13T10:00:00+00:00",
        usable_at: "2026-08-14T10:00:00+00:00",
      },
    });
    expect((await api.getMe()).operator_code).toEqual({
      issued_at: "2026-08-13T10:00:00+00:00",
      usable_at: "2026-08-14T10:00:00+00:00",
    });
    expect(await api.stopOperatorCode()).toEqual({ stopped: true });
    expect((await api.getMe()).operator_code).toBeNull();
    expect(await api.stopOperatorCode()).toEqual({ stopped: true });
  });
});

describe("the mock daily board's floor (spec A2 §9.5)", () => {
  it("serves the floor and a public flag on each row", async () => {
    const api = makeMockApi({ today: TODAY });
    const board = await api.getLeaderboard();
    expect(board.floor.played_days).toBe(3);
    // The newest played day has a full history behind it.
    expect(board.floor.caller_played_days).toBeGreaterThanOrEqual(3);
    for (const row of board.rows) {
      expect(row.public).toBe(true);
    }
  });

  it("keeps the caller's own row and marks it below the floor", async () => {
    // A day before each played day: the caller has no earlier day.
    const board = await makeMockApi({ today: TODAY }).getLeaderboard(
      "1999-01-01",
    );
    expect(board.floor).toEqual({ played_days: 3, caller_played_days: 0 });
    const own = board.rows.find((row) => row.player === "ade");
    expect(own?.public).toBe(false);
    for (const row of board.rows.filter((one) => one.player !== "ade")) {
      expect(row.public).toBe(true);
    }
  });
});
