import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import { medianDelta } from "../../src/screens/reveal";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

const api = () => makeMockApi({ today: HARNESS_TODAY });

describe("the Reveal screen", () => {
  it("derives the hero strictly from the trial row", async () => {
    const view = await api().getReveal();
    renderAt("/reveal");
    expect(
      await screen.findByText(view.trial?.p.toFixed(4) as string),
    ).toBeDefined();
    expect(
      screen.getByText(`${view.trial?.beaten} of ${view.trial?.decoy_count}`),
    ).toBeDefined();
    expect(screen.getByText(view.secret)).toBeDefined();
    expect(
      screen.getByText("printf '%s:%s' TARGET SECRET | sha256sum"),
    ).toBeDefined();
  });

  it("renders the report and the mock leaderboard", async () => {
    const view = await api().getReveal();
    const board = await api().getLeaderboard(view.day);
    renderAt("/reveal");
    await screen.findByText("What matched");
    for (const row of view.report) {
      expect(screen.getByText(row.atom_text)).toBeDefined();
    }
    await screen.findByText("Today's leaderboard");
    // The own row renders as "you", the cast by name.
    expect(screen.getByText("you")).toBeDefined();
    const named = board.rows.filter((row) => row.player !== "ade");
    for (const row of named) {
      expect(screen.getByText(row.player)).toBeDefined();
    }
  });

  it("replays the stored sketch from the mock submission", async () => {
    renderAt("/reveal");
    await screen.findByText("Your sketch");
    await screen.findByText("What matched");
    expect(screen.queryByText(/No stored sketch/)).toBeNull();
  });

  it("shows the not-revealed state for an unplayed day", async () => {
    renderAt("/reveal?day=1999-01-01");
    expect(await screen.findByText(/Not revealed yet/)).toBeDefined();
  });
});

describe("medianDelta", () => {
  const history = [
    { day: "2026-08-13", p: 0.9 },
    { day: "2026-08-12", p: 0.5 },
    { day: "2026-08-11", p: 0.7 },
    { day: "2026-08-10", p: 0.3 },
  ];

  it("subtracts the median of the prior days alone", () => {
    // Priors of 08-13: [0.3, 0.5, 0.7] -> median 0.5.
    expect(medianDelta(0.9, "2026-08-13", history)).toBeCloseTo(0.4);
  });

  it("hides below two priors", () => {
    // 08-12 has two priors (08-10, 08-11); 08-11 has one.
    expect(medianDelta(0.9, "2026-08-12", history)).not.toBeNull();
    expect(medianDelta(0.9, "2026-08-11", history)).toBeNull();
  });
});
