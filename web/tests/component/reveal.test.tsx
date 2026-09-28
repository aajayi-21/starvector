import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

const api = () => makeMockApi({ today: HARNESS_TODAY });
const pct = (p: number): string => `${Math.floor(p * 100 + 1e-9)}%`;

describe("the results screen", () => {
  it("leads with the result against chance, from the trial row alone", async () => {
    const view = await api().getReveal();
    renderAt("/reveal");
    const trial = view.trial;
    expect(
      await screen.findByText(`You beat ${pct(trial?.p ?? 0)} of the photos`),
    ).toBeDefined();
    expect(
      screen.getByText(`${trial?.beaten} of the other ${trial?.decoy_count}`),
    ).toBeDefined();
    expect(
      screen.getByRole("img", { name: /Guessing averages 50%/ }),
    ).toBeDefined();
    // No "good match" grading anywhere (spec M1 §9).
    expect(screen.queryByText(/great|excellent|strong result/i)).toBeNull();
  });

  it("credits the hidden photo and links its page", async () => {
    const view = await api().getReveal();
    renderAt("/reveal");
    const link = (await screen.findByRole("link", {
      name: view.credit?.source,
    })) as HTMLAnchorElement;
    expect(link.href).toBe(view.credit?.page);
    expect(link.target).toBe("_blank");
    expect(
      screen.getByText(new RegExp(view.credit?.title ?? "")),
    ).toBeDefined();
  });

  it("lists matched words with bars and unmatched words last", async () => {
    const view = await api().getReveal();
    renderAt("/reveal");
    const card = (await screen.findByText("What connected")).closest(
      "section",
    ) as HTMLElement;
    const matched = view.report.filter((row) => row.element !== null);
    const unmatched = view.report.filter((row) => row.element === null);
    expect(within(card).getAllByRole("img")).toHaveLength(matched.length);
    for (const row of unmatched) {
      const item = within(card).getByText(`“${row.atom_text}”`).closest("li");
      expect(item?.textContent).toMatch(/had no close match/);
    }
  });

  it("shows everyone's result for the day, with you named as you", async () => {
    const view = await api().getReveal();
    const board = await api().getLeaderboard(view.day);
    renderAt("/reveal");
    const card = (await screen.findByText("Everyone this day")).closest(
      "section",
    ) as HTMLElement;
    expect(await within(card).findByText("You")).toBeDefined();
    const named = board.rows.filter((row) => row.player !== "ade");
    for (const row of named) {
      expect(
        within(card).getAllByText(row.display_name).length,
      ).toBeGreaterThan(0);
    }
  });

  it("folds the fairness check away, with the command to run", async () => {
    const view = await api().getReveal();
    renderAt("/reveal");
    const summary = await screen.findByText("Check that this day was fair");
    fireEvent.click(summary);
    expect(screen.getByText(view.secret)).toBeDefined();
    expect(screen.getByText(view.commitment)).toBeDefined();
    expect(
      screen.getByText(
        `printf '%s:%s' ${view.target_id} ${view.secret} | sha256sum`,
      ),
    ).toBeDefined();
  });

  it("replays the stored sketch", async () => {
    const view = renderAt("/reveal");
    await screen.findByText("Your sketch");
    // Loading shows nothing, and the loaded copy replays.
    expect(screen.queryByText(/isn't stored on this device/)).toBeNull();
    await waitFor(() =>
      expect(
        view.container.querySelectorAll(".picture-frame canvas"),
      ).toHaveLength(1),
    );
    expect(screen.queryByText(/isn't stored on this device/)).toBeNull();
  });

  it("says results aren't in on the constant 404", async () => {
    const refusing: Api = {
      ...api(),
      getReveal: () =>
        Promise.reject(new ApiError(404, undefined, "not revealed")),
    };
    renderAt("/reveal?day=1999-01-01", refusing);
    expect(await screen.findByText("Results aren't in yet")).toBeDefined();
  });
});
