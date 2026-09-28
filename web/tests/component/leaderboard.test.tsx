import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import type { SkillBoardView } from "../../src/api/types";
import { evidenceSentence } from "../../src/screens/leaderboard";
import { HARNESS_TODAY, renderAt } from "./harness";

function api() {
  return makeMockApi({ today: HARNESS_TODAY });
}

/** The mock with the skill board replaced. */
function serving(view: SkillBoardView) {
  return {
    ...api(),
    getSkillLeaderboard: () => Promise.resolve(view),
  };
}

describe("the leaderboard screen", () => {
  // D5 as ruled 2026-08-21: a row with a stored avatar renders
  // the picture, and a row without one keeps the initials.
  it("renders the avatar circle on the board rows", async () => {
    const base = api();
    const withAvatar = {
      ...base,
      getLeaderboard: async (day?: string) => {
        const board = await base.getLeaderboard(day);
        const first = board.rows[0];
        if (first !== undefined) {
          first.avatar_hash = "a".repeat(64);
        }
        return board;
      },
    };
    const view = renderAt("/leaderboard", withAvatar);
    await screen.findByText("Latest day");
    // One 24 px picture for the row with a hash; the others fall
    // back to initials and render no image.
    await waitFor(() =>
      expect(
        view.container.querySelectorAll('table img[width="24"]').length,
      ).toBeGreaterThanOrEqual(1),
    );
  });

  it("serves the day's board and the ranked skill board", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt("/leaderboard");
    expect(await screen.findByText("Latest day")).toBeDefined();
    expect(await screen.findByText("Skill ranking")).toBeDefined();
    expect(await screen.findByText("Ranked players")).toBeDefined();
    // The cut is stated, never silent.
    expect(
      await screen.findByText(
        new RegExp(`Showing 25 of ${board.eligible_count} ranked`),
      ),
    ).toBeDefined();
  });

  it("draws one dot for every player, ranked or not", async () => {
    const board = await api().getSkillLeaderboard();
    const view = renderAt("/leaderboard");
    await screen.findByText("Skill ranking");
    const chart = view.container.querySelector("svg[role='img']");
    expect(chart).not.toBeNull();
    expect(chart?.querySelectorAll("circle")).toHaveLength(board.rows.length);
  });

  it("shows the rank, its range and the trial count at equal weight", async () => {
    // Spec M1 §9 and ARCHITECTURE §17. The uncertainty and the
    // trial count must not be set as a footnote, so no cell in the
    // ranked table carries the muted class or a smaller size.
    renderAt("/leaderboard");
    const table = await screen.findByTestId("ranked-table");
    for (const cell of table.querySelectorAll("td")) {
      expect(cell.className).not.toMatch(/muted|subtle|small|tiny/);
      expect(cell.getAttribute("style") ?? "").not.toContain("font-size");
      expect(cell.getAttribute("style") ?? "").not.toContain("opacity");
    }
  });

  it("renders the rank as a fraction, not a position", async () => {
    renderAt("/leaderboard");
    const table = await screen.findByTestId("ranked-table");
    const first = table.querySelector("tbody tr td");
    // A posterior expectation: 1.4, not 1.
    expect(first?.textContent).toMatch(/^\d+\.\d$/);
  });

  it("tells a player below the floor where they stand", async () => {
    const board = await api().getSkillLeaderboard();
    const rows = board.rows.map((row, index) =>
      index === 0
        ? {
            ...row,
            player: "ade",
            n: 12,
            eligible: false,
            shrunk: null,
            expected_rank: null,
            rank_low: null,
            rank_high: null,
          }
        : row,
    );
    renderAt("/leaderboard", serving({ ...board, rows }));
    expect(
      await screen.findByText(/You've sent 12 of the 30 results/),
    ).toBeDefined();
    expect(screen.getByText(/Until 30 results/)).toBeDefined();
  });

  it("gates itself with the two floors from the wire", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt(
      "/leaderboard",
      serving({
        ...board,
        active: false,
        eligible_count: 0,
        rows: [],
        population: null,
        variation: null,
        discovery: null,
      }),
    );
    // The two floors, each said as what it is: results for each
    // player, and players for the population.
    expect(
      await screen.findByText(/starts once a player has sent 30 results/),
    ).toBeDefined();
    expect(screen.getByText(/After 30 players reach 30 results/)).toBeDefined();
    expect(screen.queryByText("Ranked players")).toBeNull();
  });

  it("publishes a fitted spread of zero as a real answer", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt(
      "/leaderboard",
      serving({
        ...board,
        population: {
          ...(board.population ?? {
            mu: 0,
            mu_spread: 0,
            fitted: true,
            halvings: 60,
          }),
          tau: 0,
        },
      }),
    );
    expect(await screen.findByText(/can't be told apart yet/)).toBeDefined();
    expect(screen.getByText(/a real answer, not a missing one/)).toBeDefined();
  });

  it("refuses to read a missed level as sameness", async () => {
    // Spec M1 §6: a variation statistic that does not clear its
    // level is not evidence that the players are the same, and the
    // copy must not say it is.
    const board = await api().getSkillLeaderboard();
    renderAt(
      "/leaderboard",
      serving({
        ...board,
        variation: {
          ...(board.variation as NonNullable<SkillBoardView["variation"]>),
          q_significance: 0.4,
        },
      }),
    );
    const note = await screen.findByText(/doesn't clear its level/);
    expect(note.textContent).toContain("isn't evidence that players are");
    expect(note.textContent).not.toMatch(/players are the same\.?$/);
  });

  it("says the site-wide claim as a natural frequency", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt("/leaderboard");
    const claim = await screen.findByText(/stand out by luck alone/);
    expect(claim.textContent).toContain(
      `of ${board.discovery?.tested} players stand out above chance`,
    );
  });

  it("marks the caller by store key, never by label", async () => {
    // Two players share a display name in the mock population. A
    // screen that compares on the label lights up strangers.
    const board = await api().getSkillLeaderboard();
    renderAt("/leaderboard");
    const table = await screen.findByTestId("ranked-table");
    expect(within(table).queryAllByText("You").length).toBeLessThanOrEqual(1);
    expect(board.rows.filter((row) => row.player === "ade")).toHaveLength(1);
  });
});

describe("the evidence sentence", () => {
  it("reads 1/E as the frequency Ville's bound promises", () => {
    // Ruling 15 of 2026-08-16. With no skill the chance of ever
    // getting to 1/alpha is at most alpha, thus this frequency is
    // literally what the number promises - and unlike a
    // fixed-count value it survives the player choosing to stop.
    expect(evidenceSentence(1 / 340)).toContain("1 player in 340");
    expect(evidenceSentence(0.001)).toContain("1,000");
    // No skill shown reads as no skill shown, not as a small number.
    expect(evidenceSentence(1)).toMatch(/what no skill at all produces/);
    expect(evidenceSentence(1)).toMatch(/^Your results so far/);
    expect(evidenceSentence(0.9)).toMatch(/close to what no skill/);
  });
});
