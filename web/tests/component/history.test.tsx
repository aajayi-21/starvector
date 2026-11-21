import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { luckSentence } from "../../src/screens/history";
import { SKY_DAYS } from "../../src/sky/core";
import { makeDayNames } from "../../src/ui/day-names";
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

  it("names each day for the local date it started on, and keeps the label", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    const row = view.days[0];
    if (row === undefined) {
      throw new Error("the mock history has no day");
    }
    // The mock server's rollover hour is 22:00 UTC. The name is the one
    // that the rule gives in the zone of this machine, and the label
    // stays in the page as the identifier.
    const name = makeDayNames("22:00").long(row.day);
    const page = renderAt("/history");
    await screen.findByText("Skill number");
    await screen.findAllByText(name);
    const time = page.container.querySelector(`time[datetime="${row.day}"]`);
    expect(time?.textContent).toBe(name);
  });

  it("folds the longer explanations behind one row, words unchanged", async () => {
    renderAt("/history");
    const summary = await screen.findByText("What these numbers mean");
    const more = summary.closest("details") as HTMLDetailsElement;
    expect(more.open).toBe(false);
    expect(within(more).getByText(/steadied version/)).toBeDefined();
    expect(
      within(more).getByText(/rewards occasional strong hits/),
    ).toBeDefined();
  });

  it("states numbers and no verdict in the summary", async () => {
    renderAt("/history");
    await screen.findByText("Skill number");
    expect(
      screen.getByRole("img", {
        name: /^Skill number \d\.\d\d\. 1\.00 is chance\.$/,
      }),
    ).toBeDefined();
    for (const label of [
      "Hit number",
      "Best result",
      "Typical result",
      "Streak",
    ]) {
      expect(screen.getByText(label)).toBeDefined();
    }
    expect(
      screen.queryByText(/good|bad|well done|about the same as/i),
    ).toBeNull();
  });

  it("lists each day with a link to its results", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    renderAt("/history");
    const table = (await screen.findByText("Every day you've played")).closest(
      "section",
    ) as HTMLElement;
    // The list starts with the latest days, and one button shows the rest.
    fireEvent.click(
      within(table).getByRole("button", {
        name: `Show all ${view.days.length} days`,
      }),
    );
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
          not_scored: [],
          skill: {
            theta: 1.167,
            shrunk: 1.013,
            hit_number: 1.31,
            evidence_p: 0.258,
            n: 4,
          },
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
    // The hit number sits below the skill number (spec AG1 §7).
    expect(screen.getByTestId("hit-number").textContent).toBe("1.31");
    // Each row keeps its own pool size.
    expect(screen.getByText("3rd of 225")).toBeDefined();
    expect(screen.getByText("40th of 204")).toBeDefined();
    expect(screen.getByText(/Early estimate/)).toBeDefined();
    expect(pct(0.9911)).toBe("99%");
  });

  it("opens as a sky with one star for each day", async () => {
    const page = renderAt("/history");
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    const sky = await screen.findByRole("region", {
      name: "Your results as a sky of your sketches",
    });
    const stars = within(
      within(sky).getByRole("group", { name: "Your days, the oldest first" }),
    ).getAllByRole("button");
    // One star for each day, and the halo of the best one.
    expect(stars).toHaveLength(Math.min(view.days.length, SKY_DAYS));
    expect(sky.querySelectorAll(".sky-star.is-best")).toHaveLength(1);
    // The oldest day is the first star, as the chart runs.
    const oldest = view.days[Math.min(view.days.length, SKY_DAYS) - 1];
    expect(stars[0]?.getAttribute("aria-label")).toBe(
      `${makeDayNames("22:00").long(oldest?.day as string)}: ${Math.floor((oldest?.p as number) * 100 + 1e-9)} percent`,
    );
    // The chart that the sky settles into keeps the line of chance.
    expect(sky.querySelector('[data-sky="chance-line"]')).not.toBeNull();
    expect(screen.getByText(/dashed line is 50%/)).toBeDefined();
    // The title stands on the sky, one time.
    expect(
      within(sky).getByRole("heading", { name: "Your results" }),
    ).toBeDefined();
    expect(page.container.querySelectorAll("h1")).toHaveLength(1);
  });

  it("draws each day's sketch as a constellation", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    const page = renderAt("/history");
    await screen.findByText("Skill number");
    // A sketch arrives after the history: each day's own stored send.
    await waitFor(() =>
      expect(page.container.querySelectorAll("[data-sky-fig]")).toHaveLength(
        Math.min(view.days.length, SKY_DAYS),
      ),
    );
    const figure = page.container.querySelector("[data-sky-fig]");
    expect(figure?.querySelectorAll("polyline").length).toBeGreaterThan(0);
    // The drawings are pictures of the stars, which hold the names.
    expect(figure?.getAttribute("aria-hidden")).toBe("true");
  });

  it("keeps a day's star when the day has no stored sketch", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const view = await base.getHistory();
    const asked: string[] = [];
    const api: Api = {
      ...base,
      getSubmission: (day: string) => {
        asked.push(day);
        return Promise.reject(new Error("no stored send"));
      },
    };
    const page = renderAt("/history", api);
    const sky = await screen.findByRole("region", {
      name: "Your results as a sky of your sketches",
    });
    const count = Math.min(view.days.length, SKY_DAYS);
    const stars = within(
      within(sky).getByRole("group", { name: "Your days, the oldest first" }),
    ).getAllByRole("button");
    expect(stars).toHaveLength(count);
    // One read for each day of the sky, and no more.
    await waitFor(() => expect(asked).toHaveLength(count));
    // The day opens with its number, and says that it has no sketch.
    fireEvent.click(stars[0] as HTMLElement);
    expect(await within(sky).findByText("No sketch this day.")).toBeDefined();
    expect(page.container.querySelectorAll("[data-sky-fig]")).toHaveLength(0);
  });

  it("opens a day from its star, and steps through the days", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    renderAt("/history");
    const sky = await screen.findByRole("region", {
      name: "Your results as a sky of your sketches",
    });
    const stars = within(
      within(sky).getByRole("group", { name: "Your days, the oldest first" }),
    ).getAllByRole("button");
    const newest = view.days[0];
    const before = view.days[1];
    if (newest === undefined || before === undefined) {
      throw new Error("the mock history has fewer than two days");
    }
    const plate = within(sky).getByRole("complementary", {
      name: "The chosen day",
    });
    expect(plate.textContent).toBe("");
    fireEvent.click(stars[stars.length - 1] as HTMLElement);
    // The words state the number against the 50% mark, and no verdict.
    expect(
      within(plate).getByText(
        (_, node) =>
          node?.tagName === "P" &&
          node.textContent === `You beat ${pct(newest.p)} of the photos`,
      ),
    ).toBeDefined();
    expect(
      within(plate).getByRole("img", {
        name: /Guessing averages 50%/,
      }),
    ).toBeDefined();
    expect(
      (
        within(plate).getByRole("link", {
          name: "Photo and details",
        }) as HTMLAnchorElement
      ).href,
    ).toContain(`/reveal?day=${newest.day}`);
    expect(stars[stars.length - 1]?.getAttribute("aria-pressed")).toBe("true");
    // The newest day has no day after it.
    expect(
      (
        within(plate).getByRole("button", {
          name: "The day after",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(
      within(plate).getByRole("button", { name: "The day before" }),
    );
    expect(
      within(plate).getByText(
        (_, node) =>
          node?.tagName === "P" &&
          node.textContent === `You beat ${pct(before.p)} of the photos`,
      ),
    ).toBeDefined();
    // The arrow keys step as the buttons do, and Escape lets the day go.
    fireEvent.keyDown(document, { key: "ArrowRight" });
    expect(stars[stars.length - 1]?.getAttribute("aria-pressed")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(plate.textContent).toBe("");
    expect(screen.queryByText(/good|bad|well done/i)).toBeNull();
  });

  it("sends a player with no result to today", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getHistory: () =>
        Promise.resolve({ days: [], not_scored: [], skill: null }),
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
