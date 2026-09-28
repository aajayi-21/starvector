import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { luckSentence } from "../../src/screens/history";
import { median } from "../../src/ui/format";
import { HARNESS_TODAY, renderAt } from "./harness";

const pct = (p: number): string => `${Math.floor(p * 100 + 1e-9)}%`;

describe("the Your results screen", () => {
  it("renders the skill number in plain words", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    renderAt("/history");
    expect(
      await screen.findByText(view.skill?.theta.toFixed(2) as string),
    ).toBeDefined();
    expect(screen.getByText("Skill number")).toBeDefined();
    expect(screen.getByText(/1.00 is chance/)).toBeDefined();
    expect(
      screen.getByText(luckSentence(view.skill?.evidence_p ?? 1)),
    ).toBeDefined();
    // No jargon on the player's screen.
    expect(screen.queryByText(/shrunk/)).toBeNull();
    expect(screen.queryByText(/evidence/i)).toBeNull();
    expect(screen.queryByText(/not wired/)).toBeNull();
  });

  it("lists each day with a link to its results", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    renderAt("/history");
    const table = (await screen.findByText("Every day")).closest(
      "section",
    ) as HTMLElement;
    const links = within(table).getAllByRole("link", { name: "Details" });
    expect(links).toHaveLength(view.days.length);
    expect((links[0] as HTMLAnchorElement).href).toContain(
      `/reveal?day=${view.days[0]?.day}`,
    );
  });

  // The two repairs of docs/final-push.md §7.2, on the four days the
  // plan measured: the best is the best share beaten, and the median
  // of an even count is the mean of the two middle values.
  it("computes the best and the typical result correctly", async () => {
    const days = [
      {
        day: "2026-08-18",
        trial_code: "07V1JL",
        p: 0.8079,
        target_rank: 40,
        decoy_count: 203,
      },
      {
        day: "2026-08-17",
        trial_code: "OCRH6J",
        p: 0.0985,
        target_rank: 184,
        decoy_count: 203,
      },
      {
        day: "2026-08-13",
        trial_code: "T70EKY",
        p: 0.9911,
        target_rank: 3,
        decoy_count: 224,
      },
      {
        day: "2026-08-12",
        trial_code: "ZM5BTM",
        p: 0.9688,
        target_rank: 8,
        decoy_count: 224,
      },
    ];
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getHistory: () =>
        Promise.resolve({
          days,
          skill: { theta: 1.167, shrunk: 1.013, evidence_p: 0.258, n: 4 },
        }),
    };
    renderAt("/history", api);
    const best = (await screen.findByText("Best result")).closest(
      "section",
    ) as HTMLElement;
    expect(within(best).getByText("99%")).toBeDefined();
    const typical = screen
      .getByText("Typical result")
      .closest("section") as HTMLElement;
    // (0.8079 + 0.9688) / 2 = 0.88835, shown as 88% — not 96%.
    expect(within(typical).getByText("88%")).toBeDefined();
    // Each row keeps its own pool size.
    expect(screen.getByText("3rd of 225")).toBeDefined();
    expect(screen.getByText("40th of 204")).toBeDefined();
    expect(screen.getByText(/Early estimate/)).toBeDefined();
    expect(pct(0.9911)).toBe("99%");
  });

  it("draws the chance line on the chart", async () => {
    renderAt("/history");
    const chart = await screen.findByRole("img", {
      name: /Results for the last/,
    });
    expect(chart.querySelector(".bars-chance")).not.toBeNull();
    expect(screen.getByText(/dashed line is 50%/)).toBeDefined();
  });

  it("sends a player with no result to today", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getHistory: () => Promise.resolve({ days: [], skill: null }),
    };
    renderAt("/history", api);
    expect(await screen.findByText("No results yet")).toBeDefined();
  });
});

describe("the median", () => {
  it("is the middle value, or the mean of the two middle values", () => {
    expect(median([])).toBeUndefined();
    expect(median([3])).toBe(3);
    expect(median([1, 9, 5])).toBe(5);
    expect(median([0.8079, 0.0985, 0.9911, 0.9688])).toBeCloseTo(0.88835);
  });
});

describe("the luck sentence", () => {
  it("reads the tail probability in plain words", () => {
    expect(luckSentence(0.258)).toBe(
      "Luck alone does at least this well about 26% of the time.",
    );
    expect(luckSentence(0.0004)).toMatch(/less than 1 time in 1,000/);
    expect(luckSentence(0.004)).toMatch(/less than 1%/);
    expect(luckSentence(0.995)).toMatch(/almost every time/);
  });
});
