import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import type { DayStatus } from "../../src/api/types";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

function withDay(overrides: { status?: DayStatus; submitted?: boolean }): Api {
  const base = makeMockApi({ today: HARNESS_TODAY });
  return {
    ...base,
    getDay: async () => ({ ...(await base.getDay()), ...overrides }),
  };
}

describe("the home screen (spec BR1 §6)", () => {
  it("offers one primary step when today is open", async () => {
    renderAt("/");
    const start = await screen.findByRole("link", {
      name: "Start today's session",
    });
    expect(start.getAttribute("href")).toBe("/today");
    expect(start.className).toContain("btn-primary");
    // The one primary action on the screen.
    expect(document.querySelectorAll(".btn-primary")).toHaveLength(1);
  });

  it("says you're in when today is sent", async () => {
    renderAt("/", withDay({ submitted: true }));
    expect(await screen.findByText("You're in for today")).toBeDefined();
    expect(screen.queryByText("Start today's session")).toBeNull();
  });

  it("says results are coming while the day closes", async () => {
    renderAt("/", withDay({ status: "closing", submitted: true }));
    expect(await screen.findByText("Today's session has closed")).toBeDefined();
  });

  it("sends a revealed day to its results", async () => {
    renderAt("/", withDay({ status: "revealed", submitted: true }));
    const link = await screen.findByRole("link", { name: "See your result" });
    expect(link.getAttribute("href")).toBe("/reveal");
  });

  it("says when no session is open", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getDay: () => Promise.reject(new ApiError(404, undefined, "no day open")),
    };
    renderAt("/", api);
    expect(
      await screen.findByText("No session is open right now"),
    ).toBeDefined();
  });

  it("shows the last result against chance", async () => {
    const history = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    const latest = history.days[0];
    renderAt("/");
    expect(
      await screen.findByText(`${Math.floor((latest?.p ?? 0) * 100 + 1e-9)}%`),
    ).toBeDefined();
    expect(
      screen.getByRole("img", { name: /Guessing averages 50%/ }),
    ).toBeDefined();
  });

  it("explains the game to a player with no result yet", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getHistory: () => Promise.resolve({ days: [], skill: null }),
    };
    renderAt("/", api);
    expect(
      await screen.findByText("New here? Here's how it works"),
    ).toBeDefined();
    expect(screen.getByText("Start from the code")).toBeDefined();
  });
});
