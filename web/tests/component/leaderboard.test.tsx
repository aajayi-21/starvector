import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import type { SkillBoardView } from "../../src/api/types";
import { evidenceSentence } from "../../src/screens/leaderboard";
import { makeDayNames } from "../../src/ui/day-names";
import { HARNESS_TODAY, renderAt } from "./harness";

/** The skill ranking: the second tab of the screen. */
const SKILL = "/leaderboard?board=skill";

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
    // One picture for the row with a hash, which leads the podium; the
    // others fall back to initials and render no image. A row with a
    // streak ring draws a smaller picture inside the same circle (spec
    // H1 §4).
    await waitFor(() =>
      expect(
        view.container.querySelectorAll(".podium-place img").length,
      ).toBeGreaterThanOrEqual(1),
    );
  });

  it("serves the day's board, and the skill board behind its tab", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt("/leaderboard");
    expect(
      await screen.findByRole("list", { name: "The first three" }),
    ).toBeDefined();
    expect(screen.queryByText("Ranked players")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Skill ranking" }));
    expect(await screen.findByText("Ranked players")).toBeDefined();
    expect(
      screen
        .getByRole("tab", { name: "Skill ranking" })
        .getAttribute("aria-selected"),
    ).toBe("true");
    // The cut is stated, never silent.
    expect(
      await screen.findByText(
        new RegExp(`Showing 12 of ${board.eligible_count} ranked`),
      ),
    ).toBeDefined();
  });

  it("shows more ranked players on request", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt(SKILL);
    const table = await screen.findByTestId("ranked-table");
    const rows = (): number => table.querySelectorAll("tbody tr").length;
    const before = rows();
    fireEvent.click(screen.getByRole("button", { name: "Show more players" }));
    expect(rows()).toBeGreaterThan(before);
    expect(rows()).toBeLessThanOrEqual(board.eligible_count + 2);
  });

  it("draws the likely range of each ranked row and hides the drawing", async () => {
    // The drawing repeats the numbers of the row, so assistive
    // technology reads the numbers and skips the drawing.
    renderAt(SKILL);
    const table = await screen.findByTestId("ranked-table");
    const bars = table.querySelectorAll(".board-range-bar");
    expect(bars.length).toBeGreaterThan(0);
    for (const bar of bars) {
      expect(bar.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("shows the hit number beside the steadied skill (spec AG1 §7)", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt(SKILL);
    const table = await screen.findByTestId("ranked-table");
    expect(
      within(table).getByRole("columnheader", { name: "Hit number" }),
    ).toBeDefined();
    const first = board.rows.find((row) => row.eligible);
    expect(first).toBeDefined();
    expect(
      within(table).getAllByText((first?.hit_number ?? 0).toFixed(2)).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("draws one star for every player, ranked or not", async () => {
    const board = await api().getSkillLeaderboard();
    const view = renderAt(SKILL);
    await screen.findByText("Ranked players");
    const chart = view.container.querySelector("svg[role='img']");
    expect(chart).not.toBeNull();
    expect(chart?.querySelectorAll(".board-star")).toHaveLength(
      board.rows.length,
    );
  });

  it("shows the rank, its range and the trial count at equal weight", async () => {
    // Spec M1 §9 and ARCHITECTURE §17. The uncertainty and the
    // trial count must not be set as a footnote, so no cell in the
    // ranked table carries the muted class or a smaller size.
    renderAt(SKILL);
    const table = await screen.findByTestId("ranked-table");
    for (const cell of table.querySelectorAll("td")) {
      expect(cell.className).not.toMatch(/muted|subtle|small|tiny/);
      expect(cell.getAttribute("style") ?? "").not.toContain("font-size");
      expect(cell.getAttribute("style") ?? "").not.toContain("opacity");
    }
  });

  it("renders the rank as a fraction, not a position", async () => {
    renderAt(SKILL);
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
    renderAt(SKILL, serving({ ...board, rows }));
    expect(
      await screen.findByText(/You've sent 12 of the 30 results/),
    ).toBeDefined();
    expect(screen.getByText(/Until 30 results/)).toBeDefined();
  });

  it("gates itself with the two floors from the wire", async () => {
    const board = await api().getSkillLeaderboard();
    renderAt(
      SKILL,
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
      SKILL,
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
      SKILL,
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
    renderAt(SKILL);
    const claim = await screen.findByText(/stand out by luck alone/);
    expect(claim.textContent).toContain(
      `of ${board.discovery?.tested} players stand out above chance`,
    );
  });

  it("marks the caller by store key, never by label", async () => {
    // The username is the key and the one name (spec A2 ruling 3).
    // A screen that compares on a label lights up strangers.
    const board = await api().getSkillLeaderboard();
    renderAt(SKILL);
    const table = await screen.findByTestId("ranked-table");
    expect(within(table).queryAllByText("You").length).toBeLessThanOrEqual(1);
    expect(board.rows.filter((row) => row.player === "ade")).toHaveLength(1);
  });
});

describe("the day: the photo, the podium, and the river", () => {
  /** The mock with one player's result raised to the top of the day. */
  function leading(player: string) {
    const base = api();
    return {
      ...base,
      getLeaderboard: async (day?: string) => {
        const board = await base.getLeaderboard(day);
        const rows = board.rows
          .map((row) => (row.player === player ? { ...row, p: 0.99 } : row))
          .sort((a, b) => b.p - a.p);
        return { ...board, rows };
      },
    };
  }

  it("sets the first three on the podium in the order of the board", async () => {
    const board = await api().getLeaderboard();
    const open = board.rows.filter((row) => row.public);
    renderAt("/leaderboard");
    const podium = await screen.findByRole("list", { name: "The first three" });
    const places = within(podium).getAllByRole("listitem");
    // The first stands first in the reading order, wherever it stands
    // on the screen.
    expect(places.map((place) => place.dataset.player)).toEqual(
      open.slice(0, 3).map((row) => row.player),
    );
    expect(places[0]?.textContent).toMatch(/^1st/);
    // Each place says the result and the place of the photo, and no
    // medal or grade.
    const first = open[0];
    expect(places[0]?.textContent).toContain(
      `${Math.floor((first?.p ?? 0) * 100)}%`,
    );
    expect(places[0]?.textContent).toContain(
      `of ${(first?.decoy_count ?? 0) + 1} photos`,
    );
    expect(podium.textContent).not.toMatch(/gold|silver|bronze|medal|winner/i);
  });

  it("shows the photo with its credit, and the code once, under the title", async () => {
    const mock = api();
    const board = await mock.getLeaderboard();
    const reveal = await mock.getReveal(board.day);
    const code = (await mock.getRevealedDays()).days.find(
      (row) => row.day === board.day,
    )?.trial_code;
    renderAt("/leaderboard");
    const photo = await screen.findByAltText(reveal.credit?.title ?? "");
    const figure = photo.closest("figure") as HTMLElement;
    expect(within(figure).getByText(/Wikimedia Commons/)).toBeDefined();
    expect(code).toBeDefined();
    expect(figure.textContent).not.toContain(code);
    expect(
      (await screen.findByText(code ?? "")).closest(".board-sub"),
    ).not.toBeNull();
  });

  it("draws each sketch of the day, with a result only where the board shows one", async () => {
    // The sends hold each player, and the board hides a row below its
    // floor (spec A2 §9.5): a player with no row gets the name alone.
    const board = await api().getLeaderboard();
    const view = renderAt("/leaderboard");
    await waitFor(() =>
      expect(
        [...view.container.querySelectorAll(".river-name")].map(
          (name) => name.textContent,
        ),
      ).toContain("nightjar"),
    );
    const labels = [...view.container.querySelectorAll(".river-name")].map(
      (name) => name.textContent ?? "",
    );
    const tallgrass = board.rows.find((row) => row.player === "tallgrass");
    expect(labels).toContain(
      `tallgrass · ${Math.floor((tallgrass?.p ?? 0) * 100)}%`,
    );
    expect(labels.some((label) => label.startsWith("nightjar ·"))).toBe(false);
    // A send with no sketch is not in the river.
    expect(labels.some((label) => label.startsWith("hollis-r"))).toBe(false);
    // The river is a picture: a reader of the page gets the board.
    expect(
      view.container.querySelector(".river")?.getAttribute("aria-hidden"),
    ).toBe("true");
  });

  it("reads each page of the sends for the sketches of the podium", async () => {
    // The mock pages its sends five at a time, the newest first, and
    // marlow sent first: the sketch is on the last page.
    const view = renderAt("/leaderboard", leading("marlow"));
    await waitFor(() =>
      expect(
        view.container.querySelector(
          '.podium-place[data-player="marlow"] .podium-sketch',
        ),
      ).not.toBeNull(),
    );
  });

  it("says so where a podium send holds no sketch", async () => {
    renderAt("/leaderboard", leading("hollis-r"));
    const podium = await screen.findByRole("list", { name: "The first three" });
    expect(await within(podium).findByText("Words only")).toBeDefined();
  });

  it("steps to the day before, and opens a calendar of revealed days", async () => {
    const days = (await api().getRevealedDays()).days;
    const names = makeDayNames("22:00");
    renderAt("/leaderboard");
    await screen.findByRole("list", { name: "The first three" });
    expect(
      (screen.getByLabelText("The day after") as HTMLButtonElement).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByLabelText("The day before"));
    const second = names.long(days[1]?.day ?? "");
    const date = await screen.findByRole("button", { name: second });
    fireEvent.click(date);
    const calendar = screen.getByRole("dialog", { name: "Pick a day" });
    expect(
      within(calendar)
        .getByRole("button", { name: second })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(within(calendar).queryByText("Surprise me")).toBeNull();
    fireEvent.click(
      within(calendar).getByRole("button", {
        name: names.long(days[0]?.day ?? ""),
      }),
    );
    expect(
      await screen.findByRole("button", {
        name: names.long(days[0]?.day ?? ""),
      }),
    ).toBeDefined();
    expect(screen.queryByRole("dialog", { name: "Pick a day" })).toBeNull();
  });

  it("brings the caller's own row into view with Find me", async () => {
    // jsdom has no scrolling: the test stands in for it.
    const original = Element.prototype.scrollIntoView;
    const scrolled: Element[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    try {
      const view = renderAt("/leaderboard");
      await screen.findByRole("table");
      fireEvent.click(screen.getByRole("button", { name: "Find me" }));
      // The own row is a place on the podium or a row of the table.
      expect(scrolled).toHaveLength(1);
      expect(scrolled[0]).toBe(
        view.container.querySelector('[data-player="ade"]'),
      );
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });
});

describe("the daily board after spec A2 (ruling 3, §9.5)", () => {
  /** The mock with the daily board's own row and floor replaced. */
  function daily(own: { public: boolean }, played: number) {
    const base = api();
    return {
      ...base,
      getLeaderboard: async (day?: string) => {
        const board = await base.getLeaderboard(day);
        return {
          ...board,
          rows: board.rows.map((row) =>
            row.player === "ade" ? { ...row, public: own.public } : row,
          ),
          floor: { played_days: 3, caller_played_days: played },
        };
      },
    };
  }

  /** The day's board: the podium, the river, and the table. */
  async function dailyCard(): Promise<HTMLElement> {
    const card = await screen.findByRole("tabpanel");
    await within(card).findByRole("table");
    return card;
  }

  it("shows the username on each row, on the podium or in the table", async () => {
    const board = await api().getLeaderboard();
    renderAt("/leaderboard");
    const card = await dailyCard();
    for (const row of board.rows.filter((one) => one.player !== "ade")) {
      expect(within(card).getAllByText(row.player).length).toBeGreaterThan(0);
    }
    // Each row once: three on the podium, and the rest in the table
    // under its head row.
    const podium = within(card).getAllByRole("listitem");
    expect(podium).toHaveLength(3);
    expect(within(card).getAllByRole("row")).toHaveLength(
      board.rows.length - podium.length + 1,
    );
  });

  it("marks nothing for a caller who is past the floor", async () => {
    renderAt("/leaderboard", daily({ public: true }, 9));
    const card = await dailyCard();
    expect(within(card).getByText("You")).toBeDefined();
    expect(within(card).queryByText("Only you can see this row")).toBeNull();
    expect(within(card).queryByTestId("board-floor")).toBeNull();
  });

  it("marks the caller's own row below the floor, with the two counts", async () => {
    renderAt("/leaderboard", daily({ public: false }, 2));
    const card = await dailyCard();
    const badge = await within(card).findByText("Only you can see this row");
    // The mark is on the caller's row and on no other.
    expect(badge.closest("tr")?.className).toBe("is-you");
    expect(within(card).getAllByText("Only you can see this row")).toHaveLength(
      1,
    );
    // The line reads the floor from the wire: 3 needed, 2 played.
    expect(within(card).getByTestId("board-floor").textContent).toBe(
      "Only you can see your row for now. It shows to other players once " +
        "you have played on 3 earlier days, and you have played on 2.",
    );
  });

  it("builds the line from the wire's floor and holds no number of its own", async () => {
    const base = daily({ public: false }, 0);
    renderAt("/leaderboard", {
      ...base,
      getLeaderboard: async (day?: string) => ({
        ...(await base.getLeaderboard(day)),
        floor: { played_days: 5, caller_played_days: 4 },
      }),
    });
    const card = await dailyCard();
    expect(within(card).getByTestId("board-floor").textContent).toContain(
      "played on 5 earlier days, and you have played on 4.",
    );
  });

  it("serves the mock's own floor: a day with no earlier play", async () => {
    // The mock marks its own row on a day before each played day.
    const base = api();
    renderAt("/leaderboard", {
      ...base,
      getLeaderboard: () => base.getLeaderboard("1999-01-01"),
    });
    const card = await dailyCard();
    expect(
      await within(card).findByText("Only you can see this row"),
    ).toBeDefined();
    expect(within(card).getByTestId("board-floor").textContent).toContain(
      "and you have played on 0.",
    );
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
