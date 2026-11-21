import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import type { DayStatus } from "../../src/api/types";
import { ApiError } from "../../src/api/types";
import { makeDayNames } from "../../src/ui/day-names";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

const SEND_FIRST = "The sketches open after you send yours.";

function withDay(
  base: Api,
  overrides: { status?: DayStatus; submitted?: boolean; sends?: number },
): Api {
  return {
    ...base,
    getDay: async () => ({ ...(await base.getDay()), ...overrides }),
  };
}

describe("the send count opens the sketches of the day (spec SS1 §7.3)", () => {
  it("is a control on the home screen, with the same words", async () => {
    renderAt("/");
    const count = await screen.findByTestId("send-count");
    expect(count.textContent).toBe("12 players have sent today");
    const link = within(count).getByRole("link");
    expect(link.getAttribute("href")).toBe(`/sends?day=${HARNESS_TODAY}`);
  });

  it("stays text when nobody sent", async () => {
    renderAt("/", withDay(makeMockApi({ today: HARNESS_TODAY }), { sends: 0 }));
    const count = await screen.findByTestId("send-count");
    expect(count.textContent).toBe("Be the first to send today");
    expect(within(count).queryByRole("link")).toBeNull();
  });

  it("is a control on the Play screen too", async () => {
    renderAt("/today");
    const count = await screen.findByTestId("play-brief-count");
    expect(within(count).getByRole("link").getAttribute("href")).toBe(
      `/sends?day=${HARNESS_TODAY}`,
    );
  });
});

describe("the sends screen: send, then see (spec SS1 §4)", () => {
  it("asks a player with no send to send first, and asks the server for nothing", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const getSends = vi.fn(base.getSends);
    renderAt("/sends", { ...base, getSends });
    expect(await screen.findByText(SEND_FIRST)).toBeDefined();
    expect(screen.getByTestId("sends-count").textContent).toBe(
      "12 players have sent today",
    );
    const start = screen.getByRole("link", { name: "Start today's sketch" });
    expect(start.getAttribute("href")).toBe("/today");
    expect(screen.queryByRole("list", { name: "Sketches" })).toBeNull();
    // The rule is the server's too, and the screen does not test it
    // with a request: a player with no send learns nothing.
    expect(getSends).not.toHaveBeenCalled();
  });

  it("keeps a closed day shut for a player with no send", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const getSends = vi.fn(base.getSends);
    renderAt("/sends", {
      ...withDay(base, { status: "closed" }),
      getSends,
    });
    expect(
      await screen.findByText("The sketches open when the photo is revealed."),
    ).toBeDefined();
    expect(
      screen.queryByRole("link", { name: "Start today's sketch" }),
    ).toBeNull();
    expect(getSends).not.toHaveBeenCalled();
  });

  it("shows the sketches to a player who sent, the newest first", async () => {
    renderAt(
      `/sends?day=${HARNESS_TODAY}`,
      makeMockApi({ today: HARNESS_TODAY, submittedToday: true }),
    );
    expect(
      await screen.findByRole("heading", { name: "Today's sketches" }),
    ).toBeDefined();
    const list = await screen.findByRole("list", { name: "Sketches" });
    const tiles = within(list).getAllByRole("listitem");
    expect(tiles).toHaveLength(5);
    // The caller's own sketch is the newest send.
    expect(within(tiles[0] as HTMLElement).getByText("You")).toBeDefined();
    expect(
      within(tiles[0] as HTMLElement).getByRole("img", {
        name: "Your sketch",
      }),
    ).toBeDefined();
    expect(screen.getByRole("status").textContent).toBe("Showing 5 of 13");
    expect(screen.queryByText(SEND_FIRST)).toBeNull();
  });

  it("draws a sketch as lines, with the color of each stroke", async () => {
    const view = renderAt(
      "/sends",
      makeMockApi({ today: HARNESS_TODAY, submittedToday: true }),
    );
    await screen.findByRole("list", { name: "Sketches" });
    const picture = view.container.querySelector(".sketch-thumb");
    const lines = picture?.querySelectorAll("polyline") ?? [];
    expect(lines.length).toBeGreaterThan(0);
    const colors = Array.from(lines).map((line) => line.getAttribute("stroke"));
    // Ink where the stroke has no color, and the stroke's own color.
    expect(colors).toContain("#eceff4");
    expect(colors).toContain("#81a1c1");
    expect(picture?.getAttribute("viewBox")).toBe("0 0 100 100");
  });

  it("loads the earlier sends with Show more, to the first send", async () => {
    renderAt(
      "/sends",
      makeMockApi({ today: HARNESS_TODAY, submittedToday: true }),
    );
    const list = await screen.findByRole("list", { name: "Sketches" });
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => {
      expect(within(list).getAllByRole("listitem")).toHaveLength(10);
    });
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => {
      expect(within(list).getAllByRole("listitem")).toHaveLength(13);
    });
    expect(screen.getByRole("status").textContent).toBe("Showing 13 of 13");
    expect(screen.queryByRole("button", { name: "Show more" })).toBeNull();
    // A send with no sketch, a withheld send, and a deleted account.
    expect(within(list).getByText("Words only")).toBeDefined();
    expect(within(list).getByText("Withheld")).toBeDefined();
    expect(within(list).getByText(/^anon-/)).toBeDefined();
  });

  it("opens an earlier day by its name", async () => {
    const day = "2026-08-01";
    renderAt(`/sends?day=${day}`);
    const name = makeDayNames("22:00").long(day);
    expect(
      await screen.findByRole("heading", { name: `Sketches of ${name}` }),
    ).toBeDefined();
    expect(await screen.findByRole("list", { name: "Sketches" })).toBeDefined();
    // The count of the day in play is not the count of this day.
    expect(screen.queryByTestId("sends-count")).toBeNull();
  });

  it("reads the server's refusal as send first", async () => {
    // The day view is out of date: it says sent, and the server has no
    // send of this player.
    const base = makeMockApi({ today: HARNESS_TODAY });
    renderAt("/sends", withDay(base, { submitted: true }));
    expect(await screen.findByText(SEND_FIRST)).toBeDefined();
  });

  it("says a failure and tries again", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY, submittedToday: true });
    let fail = true;
    const api: Api = {
      ...base,
      getSends: (day, before) =>
        fail ? Promise.reject(new ApiError(500)) : base.getSends(day, before),
    };
    renderAt("/sends", api);
    const alert = await screen.findByRole("alert");
    fail = false;
    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("list", { name: "Sketches" })).toBeDefined();
  });

  it("opens the sketches after a send on the Play screen", async () => {
    // The send makes the day view say sent, and the sends answer opens.
    const api = makeMockApi({ today: HARNESS_TODAY });
    await api.submit(HARNESS_TODAY, {
      impressions: ["cold"],
      canvas_strokes: [],
      groups: [],
      relations: [],
      pasted_text: null,
    });
    renderAt("/sends", api);
    const list = await screen.findByRole("list", { name: "Sketches" });
    // A send with no sketch is the caller's own here.
    const first = within(list).getAllByRole("listitem")[0] as HTMLElement;
    expect(within(first).getByText("You")).toBeDefined();
    expect(within(first).getByText("Words only")).toBeDefined();
  });
});
