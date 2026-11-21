import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import type { DayStatus } from "../../src/api/types";
import { ApiError } from "../../src/api/types";
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

  it("ends each lower card with one link", async () => {
    renderAt("/");
    const card = (heading: string): HTMLElement =>
      screen
        .getByRole("heading", { name: heading })
        .closest("section") as HTMLElement;
    await screen.findByRole("link", { name: "See details" });
    const links: ReadonlyArray<[string, string, string]> = [
      ["Your last result", "See details", "/reveal?day="],
      ["Streak", "Your results", "/history"],
      ["Practice", "Practice now", "/practice"],
    ];
    for (const [heading, name, href] of links) {
      const inCard = within(card(heading)).getAllByRole("link");
      expect(inCard).toHaveLength(1);
      expect(inCard[0]?.textContent).toBe(name);
      expect(inCard[0]?.getAttribute("href")).toContain(href);
    }
  });

  it("counts the revealed days of the last week from the history", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const [history, day] = await Promise.all([
      base.getHistory(),
      base.getDay(),
    ]);
    const played = new Set(history.days.map((row) => row.day));
    let count = 0;
    for (let back = 1; back <= 7; back += 1) {
      const date = new Date(`${day.day}T12:00:00Z`);
      date.setUTCDate(date.getUTCDate() - back);
      if (played.has(date.toISOString().slice(0, 10))) {
        count += 1;
      }
    }
    renderAt("/");
    expect(
      await screen.findByText(
        `You have a result on ${count} of the last 7 days.`,
      ),
    ).toBeDefined();
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
