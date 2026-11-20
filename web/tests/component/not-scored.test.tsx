import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { HARNESS_TODAY, renderAt } from "./harness";

describe("a send the close could not score (spec CR1 §7)", () => {
  it("says so on the reveal, with no other words", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getReveal: async (day?: string) => ({
        ...(await base.getReveal(day)),
        trial: null,
        report: [],
        quarantined: true,
      }),
    };
    renderAt("/reveal", api);
    expect((await screen.findByTestId("not-scored")).textContent).toContain(
      "We couldn't score your send this day.",
    );
    expect(screen.queryByText(/didn't send a sketch/)).toBeNull();
  });

  it("lists the day as not scored among the scored days", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const history = await base.getHistory();
    const newest = history.days[0];
    const oldest = history.days[history.days.length - 1];
    if (newest === undefined || oldest === undefined) {
      throw new Error("the mock history is empty");
    }
    const api: Api = {
      ...base,
      getHistory: async () => ({
        ...history,
        // One day older than each scored day, one between them.
        not_scored: [
          { day: "2026-01-02", trial_code: "OLD111" },
          { day: oldest.day, trial_code: "MID222" },
        ],
      }),
    };
    renderAt("/history", api);
    const table = (await screen.findByText("Every day you've played")).closest(
      "section",
    ) as HTMLElement;
    // The oldest day is past the first rows: one button shows each day.
    fireEvent.click(within(table).getByRole("button", { name: /^Show all / }));
    const rows = within(table).getAllByTestId("not-scored-row");
    expect(rows).toHaveLength(2);
    expect(rows[rows.length - 1]?.textContent).toContain("OLD111");
    expect(within(table).getAllByText("Not scored")).toHaveLength(2);
  });

  it("notes the day on an empty history", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getHistory: () =>
        Promise.resolve({
          days: [],
          not_scored: [{ day: "2026-08-12", trial_code: "ABC123" }],
          skill: null,
        }),
    };
    renderAt("/history", api);
    expect(
      (await screen.findByTestId("not-scored-note")).textContent,
    ).toContain("couldn't score your send");
  });
});
