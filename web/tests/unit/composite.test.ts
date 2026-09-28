import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { composeApi } from "../../src/api/client";
import { ApiError, friendlyMessage } from "../../src/api/types";

function spy(name: string): (...args: unknown[]) => Promise<string> {
  return () => Promise.resolve(name);
}

function adapter(prefix: string): Api {
  return {
    getDay: spy(`${prefix}:getDay`),
    submit: spy(`${prefix}:submit`),
    getReveal: (day?: string) =>
      Promise.resolve(
        day === undefined ? `${prefix}:getReveal` : `${prefix}:byDay`,
      ),
    imageUrl: () => `${prefix}:imageUrl`,
    getPracticeDays: spy(`${prefix}:getPracticeDays`),
    scorePractice: spy(`${prefix}:scorePractice`),
    getHistory: spy(`${prefix}:getHistory`),
    getLeaderboard: spy(`${prefix}:getLeaderboard`),
    getSkillLeaderboard: spy(`${prefix}:getSkillLeaderboard`),
    getSubmission: spy(`${prefix}:getSubmission`),
    getMe: spy(`${prefix}:getMe`),
  } as unknown as Api;
}

const live = adapter("live");
const mock = adapter("mock");

describe("the composite client", () => {
  it("serves every surface live (spec S2 made the contract real)", async () => {
    const api = composeApi(live, mock, "composite");
    expect(await api.getDay()).toBe("live:getDay");
    expect(await api.getHistory()).toBe("live:getHistory");
    expect(await api.getLeaderboard("2026-08-01")).toBe("live:getLeaderboard");
    expect(await api.getSubmission("2026-08-01")).toBe("live:getSubmission");
    expect(await api.getMe()).toBe("live:getMe");
    expect(await api.getReveal()).toBe("live:getReveal");
    expect(await api.getReveal("2026-08-01")).toBe("live:byDay");
  });

  it("serves everything from the mock in full-mock mode", async () => {
    const full = composeApi(live, mock, "mock");
    expect(await full.getDay()).toBe("mock:getDay");
    expect(await full.getHistory()).toBe("mock:getHistory");
    expect(await full.getReveal("2026-08-01")).toBe("mock:byDay");
  });
});

describe("friendlyMessage", () => {
  it("maps known causes and hides the raw token", () => {
    const copy = friendlyMessage(new ApiError(409, "already-submitted"));
    expect(copy).toBe("You've already sent today's session.");
    expect(copy).not.toContain("already-submitted");
    expect(friendlyMessage(new ApiError(409, "day-closed"))).toContain(
      "closed",
    );
  });

  it("says each intake refusal in plain words, not the server's detail", () => {
    const detail = "min-strokes: 1 strokes, minimum 2";
    for (const cause of [
      "min-ink",
      "min-strokes",
      "text-length",
      "atom-count",
      "no-scoreable-atom",
      "bad-shape",
    ]) {
      const copy = friendlyMessage(new ApiError(400, cause, detail));
      expect(copy).not.toContain(cause);
      expect(copy).not.toContain(detail);
      expect(copy).not.toMatch(/atom|channel|gate/);
    }
  });

  it("falls back to the refusal's detail for an unknown cause", () => {
    expect(
      friendlyMessage(new ApiError(400, "something-new", "Plain detail.")),
    ).toBe("Plain detail.");
  });

  it("reads a network failure as no connection", () => {
    const copy = "Can't reach Starvector. Check your connection and try again.";
    expect(friendlyMessage(new ApiError(0))).toBe(copy);
    expect(friendlyMessage(new TypeError("fetch failed"))).toBe(copy);
  });
});
