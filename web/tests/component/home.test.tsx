import { screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import type { DayStatus } from "../../src/api/types";
import { ApiError } from "../../src/api/types";
import { CROWN_DAYS } from "../../src/sky/home";
import { makeDayNames } from "../../src/ui/day-names";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

function withDay(overrides: {
  status?: DayStatus;
  submitted?: boolean;
  sends?: number;
}): Api {
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
      name: "Start today's sketch",
    });
    expect(start.getAttribute("href")).toBe("/today");
    expect(start.className).toContain("btn-primary");
    // The one primary action on the screen.
    expect(document.querySelectorAll(".btn-primary")).toHaveLength(1);
  });

  it("says you're in when today is sent", async () => {
    renderAt("/", withDay({ submitted: true }));
    expect(await screen.findByText("You're in for today")).toBeDefined();
    expect(screen.queryByText("Start today's sketch")).toBeNull();
  });

  it("says results are coming while the day closes", async () => {
    renderAt("/", withDay({ status: "closing", submitted: true }));
    expect(await screen.findByText("Today has closed")).toBeDefined();
  });

  it("sends a revealed day to its results", async () => {
    renderAt("/", withDay({ status: "revealed", submitted: true }));
    const link = await screen.findByRole("link", { name: "See your result" });
    expect(link.getAttribute("href")).toBe("/reveal");
  });

  it.each([
    [0, "Be the first to send today"],
    [1, "1 player has sent today"],
    [2, "2 players have sent today"],
    [1234, "1,234 players have sent today"],
  ])("shows %i sends as the right text (spec H1 §3)", async (sends, text) => {
    renderAt("/", withDay({ sends }));
    expect((await screen.findByTestId("send-count")).textContent).toBe(text);
  });

  it.each([
    "closing",
    "closed",
    "revealed",
  ] as const)("says no one sent when a %s day has zero sends", async (status) => {
    renderAt("/", withDay({ status, sends: 0, submitted: false }));
    expect((await screen.findByTestId("send-count")).textContent).toBe(
      "No one sent today",
    );
  });

  it.each([
    "open",
    "closing",
    "closed",
    "revealed",
  ] as const)("shows the send count when the day is %s", async (status) => {
    renderAt("/", withDay({ status, sends: 7, submitted: true }));
    expect((await screen.findByTestId("send-count")).textContent).toBe(
      "7 players have sent today",
    );
  });

  it("says when no session is open", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getDay: () => Promise.reject(new ApiError(404, undefined, "no day open")),
    };
    renderAt("/", api);
    expect(await screen.findByText("No day is open right now")).toBeDefined();
  });

  it("shows the streak as a crown: one star for each day in a row", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const me = await base.getMe();
    expect(me.streak).toBeGreaterThan(0);
    const view = renderAt("/");
    const label = await screen.findByTestId("streak-label");
    expect(label.textContent).toBe(`${me.streak}-day streak`);
    const crown = screen.getByRole("group", { name: "Your streak" });
    // The stars follow the history, which answers after the streak does.
    await waitFor(() =>
      expect(view.container.querySelectorAll(".crown-star")).toHaveLength(
        Math.min(me.streak, CROWN_DAYS),
      ),
    );
    // Each star of a day with a result opens that day.
    const stars = within(crown).getAllByRole("link");
    expect(stars[0]?.getAttribute("href")).toContain("/reveal?day=");
    expect(stars[0]?.getAttribute("aria-label")).toMatch(
      /you beat \d+% of the photos$/,
    );
  });

  it("says the streak and nothing after it", async () => {
    renderAt("/");
    const label = await screen.findByTestId("streak-label");
    expect(label.textContent).toMatch(/^\d+-day streak$/);
  });

  it("says when there is no streak", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getMe: async () => ({ ...(await base.getMe()), streak: 0 }),
    };
    const view = renderAt("/", api);
    const label = await screen.findByTestId("streak-label");
    expect(label.textContent).toBe("No streak yet");
    expect(view.container.querySelectorAll(".crown-star")).toHaveLength(0);
  });

  it.each([
    [{ submitted: false }, "Today: not sent yet"],
    [{ submitted: true }, "Today: your sketch is in"],
    [{ status: "closed" as const, submitted: false }, "Today: not sent"],
  ])("keeps a place for today on the crown: %o", async (overrides, name) => {
    renderAt("/", withDay(overrides));
    await screen.findByTestId("streak-label");
    expect(await screen.findByRole("img", { name })).toBeDefined();
  });

  it("has no place for today when the day is revealed", async () => {
    const view = renderAt(
      "/",
      withDay({ status: "revealed", submitted: true }),
    );
    await screen.findByTestId("streak-label");
    await screen.findByRole("link", { name: "See your result" });
    expect(view.container.querySelector(".crown-today")).toBeNull();
  });

  it("shows the code of the day in each state of the day", async () => {
    const day = await makeMockApi({ today: HARNESS_TODAY }).getDay();
    const code = `Code ${[...day.trial_code].join(" ")}`;
    for (const overrides of [
      {},
      { submitted: true },
      { status: "closing" as const, submitted: true },
      { status: "revealed" as const, submitted: true },
    ]) {
      const view = renderAt("/", withDay(overrides));
      expect(await screen.findByRole("img", { name: code })).toBeDefined();
      view.unmount();
    }
  });

  it("has nothing after the first screen", async () => {
    renderAt("/");
    await screen.findByRole("link", { name: "Start today's sketch" });
    for (const heading of ["Your last result", "Streak", "Practice"]) {
      expect(screen.queryByRole("heading", { name: heading })).toBeNull();
    }
  });

  it("counts down in the line under the greeting", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({
        ...(await base.getDay()),
        closes_at: "2099-01-01T22:00:00+00:00",
      }),
    };
    renderAt("/", api);
    expect(
      await screen.findByText(/Today closes in \d+ h .*\(.*\d:\d\d.*\)/),
    ).toBeDefined();
  });

  it("gives the day in play no calendar date", async () => {
    const view = renderAt("/");
    await screen.findByRole("link", { name: "Start today's sketch" });
    expect(view.container.querySelector(".eyebrow")?.textContent).toBe("Today");
  });

  it("names a day that is not open for the local date it started on", async () => {
    // The mock server's rollover hour is 22:00 UTC. The name is the one
    // that the rule gives in the zone of this machine.
    const name = makeDayNames("22:00").long(HARNESS_TODAY);
    const view = renderAt(
      "/",
      withDay({ status: "revealed", submitted: true }),
    );
    await screen.findByRole("link", { name: "See your result" });
    await screen.findByText(name, { selector: ".eyebrow" });
    expect(view.container.querySelector(".eyebrow")?.textContent).toBe(name);
  });

  it("explains the game to a player with no result yet", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getHistory: () =>
        Promise.resolve({ days: [], not_scored: [], skill: null }),
    };
    renderAt("/", api);
    expect(
      await screen.findByText("New here? Here's how it works"),
    ).toBeDefined();
    expect(screen.getByText("Start from the code")).toBeDefined();
  });
});
