import { describe, expect, it } from "vitest";

import type { Api, DayApi, PracticeApi } from "../../src/api/client";
import { composeApi } from "../../src/api/client";
import { ApiError, friendlyMessage } from "../../src/api/types";

function spy(name: string): (...args: unknown[]) => Promise<string> {
  return () => Promise.resolve(name);
}

const live = {
  getDay: spy("live:getDay"),
  submit: spy("live:submit"),
  getReveal: (day?: string) =>
    Promise.resolve(day === undefined ? "live:getReveal" : "live:byDay"),
  imageUrl: () => "live:imageUrl",
  getPracticeDays: spy("live:getPracticeDays"),
  scorePractice: spy("live:scorePractice"),
} as unknown as DayApi & PracticeApi;

const mock = {
  getDay: spy("mock:getDay"),
  submit: spy("mock:submit"),
  getReveal: (day?: string) =>
    Promise.resolve(day === undefined ? "mock:getReveal" : "mock:byDay"),
  imageUrl: () => "mock:imageUrl",
  getPracticeDays: spy("mock:getPracticeDays"),
  scorePractice: spy("mock:scorePractice"),
  getHistory: spy("mock:getHistory"),
  getLeaderboard: spy("mock:getLeaderboard"),
  getSubmission: spy("mock:getSubmission"),
  getMe: spy("mock:getMe"),
} as unknown as Api;

describe("the composite client", () => {
  const api = composeApi(live, mock, "composite");

  it("routes live surfaces to the live adapter", async () => {
    expect(await api.getDay()).toBe("live:getDay");
    expect(
      await api.submit({
        impressions: [],
        canvas_strokes: [],
        groups: [],
        relations: [],
        pasted_text: null,
      }),
    ).toBe("live:submit");
    expect(await api.getPracticeDays()).toBe("live:getPracticeDays");
    expect(api.imageUrl("x")).toBe("live:imageUrl");
  });

  it("routes contract surfaces to the mock adapter", async () => {
    expect(await api.getHistory()).toBe("mock:getHistory");
    expect(await api.getLeaderboard("2026-08-01")).toBe("mock:getLeaderboard");
    expect(await api.getSubmission("2026-08-01")).toBe("mock:getSubmission");
    expect(await api.getMe()).toBe("mock:getMe");
  });

  it("splits getReveal on the day argument", async () => {
    expect(await api.getReveal()).toBe("live:getReveal");
    expect(await api.getReveal("2026-08-01")).toBe("mock:byDay");
  });

  it("serves everything from the mock in full-mock mode", async () => {
    const full = composeApi(live, mock, "mock");
    expect(await full.getDay()).toBe("mock:getDay");
    expect(await full.getReveal()).toBe("mock:getReveal");
  });
});

describe("friendlyMessage", () => {
  it("maps known causes and hides the raw token", () => {
    const copy = friendlyMessage(new ApiError(409, "already-submitted"));
    expect(copy).toBe("Already sent — one send per day.");
    expect(copy).not.toContain("already-submitted");
    expect(friendlyMessage(new ApiError(409, "day-closed"))).toContain(
      "closed",
    );
  });

  it("prefers the refusal's own detail for gate causes", () => {
    const detail =
      "no atom reads into a weighted channel - add an impression, a " +
      "labeled group, or strokes";
    expect(
      friendlyMessage(new ApiError(400, "no-scoreable-atom", detail)),
    ).toBe(detail);
  });

  it("reads network failure as the server not answering", () => {
    expect(friendlyMessage(new ApiError(0))).toBe("The server did not answer.");
    expect(friendlyMessage(new TypeError("fetch failed"))).toBe(
      "The server did not answer.",
    );
  });
});
