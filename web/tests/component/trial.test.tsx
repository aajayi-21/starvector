import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import type { WireRecord } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const SKETCH: WireRecord = {
  impressions: ["a secret word of the player", "second line"],
  canvas_strokes: [
    {
      points: [
        [0.2, 0.2],
        [0.6, 0.6],
      ],
      group_id: null,
    },
    {
      points: [
        [0.3, 0.7],
        [0.8, 0.4],
      ],
      group_id: null,
    },
  ],
  groups: [],
  relations: [],
  pasted_text: null,
};

/** A mock world with settled trials of its first player. */
async function played(
  records: WireRecord[] = [SKETCH],
  options: Parameters<typeof makeMockApi>[0] = {},
): Promise<{ api: Api; paths: string[] }> {
  const api = makeMockApi({
    today: HARNESS_TODAY,
    instantPendingReads: 0,
    ...options,
  });
  const paths: string[] = [];
  for (const record of records) {
    const open = await api.startInstant();
    await api.sendInstant(open.date, open.trial_id, record);
    paths.push(`/t/${open.date}/${open.trial_id}`);
  }
  return { api, paths };
}

describe("the public page of an instant trial (spec IM1 §10)", () => {
  it("opens for a browser with no session", async () => {
    const { api, paths } = await played();
    await api.signOut();
    renderAt(paths[0] ?? "", api);
    expect(
      await screen.findByRole("heading", { level: 1, name: /^\d+% by ade$/ }),
    ).toBeDefined();
    // The chrome of a public path: the brand and the way to sign in.
    expect(screen.getByRole("link", { name: "Sign in" })).toBeDefined();
    expect(
      screen.getByRole("img", { name: "The sketch of ade" }),
    ).toBeDefined();
    expect(
      screen.getByText(/matched this photo better than \d+ of the other/),
    ).toBeDefined();
  });

  it("shows the sketch alone, and says how many typed lines it leaves out", async () => {
    const { api, paths } = await played();
    renderAt(paths[0] ?? "", api);
    await screen.findByRole("heading", { level: 1, name: /% by ade$/ });
    expect(screen.queryByText(/a secret word of the player/)).toBeNull();
    expect(
      screen.getByText(/sent with 2 typed lines that this page does not show/),
    ).toBeDefined();
  });

  it("puts the trial in the record of its owner", async () => {
    const { api, paths } = await played([SKETCH, SKETCH, SKETCH]);
    renderAt(paths[1] ?? "", api);
    const record = await screen.findByText(/Trial 2 of 3/);
    const line = record.closest("p") as HTMLElement;
    expect(line.textContent).toMatch(
      /The average of all 3 with a result is \d+%/,
    );
    expect(line.textContent).toMatch(/Chance is 50%/);
    expect(line.textContent).toMatch(/no trial can be removed/);
  });

  it("says when a trial was words only", async () => {
    const { api, paths } = await played([{ ...SKETCH, canvas_strokes: [] }]);
    renderAt(paths[0] ?? "", api);
    expect(
      await screen.findByText("This trial was sent with words only."),
    ).toBeDefined();
    expect(screen.queryByRole("img", { name: /The sketch of/ })).toBeNull();
  });

  it("names a guest as a guest, and not by its identifier", async () => {
    const { api, paths } = await played([SKETCH], {
      signedIn: false,
      guest: true,
    });
    renderAt(paths[0] ?? "", api);
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /^\d+% by a guest$/,
      }),
    ).toBeDefined();
    expect(screen.queryByText(/guest-0123456789abcdef/)).toBeNull();
  });

  it("has the check, with the command and the saved file", async () => {
    const { api, paths } = await played();
    renderAt(paths[0] ?? "", api);
    const summary = await screen.findByText(
      "How the photo was picked, and how to check it",
    );
    const check = summary.closest("details") as HTMLElement;
    expect(
      within(check).getByText(
        "uv run python tools/check_instant.py --trial trial.json",
      ),
    ).toBeDefined();
    expect(
      within(check).getByRole("button", { name: "Save trial.json" }),
    ).toBeDefined();
    // A test beacon proves nothing, and the page says so.
    expect(within(check).getByText(/used a test beacon/)).toBeDefined();
  });

  it("says that a trial has no public page", async () => {
    const api = makeMockApi({ today: HARNESS_TODAY });
    await api.signOut();
    renderAt(`/t/${HARNESS_TODAY}/${"f".repeat(32)}`, api);
    expect(
      await screen.findByText(/This trial has no public page/),
    ).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Try an instant trial" }),
    ).toBeDefined();
  });

  it("opens inside the app for a signed-in player", async () => {
    const { api, paths } = await played();
    renderAt(paths[0] ?? "", api);
    await screen.findByRole("heading", { level: 1, name: /% by ade$/ });
    expect(screen.getByLabelText("Your account")).toBeDefined();
  });
});

describe("Share on an instant result (spec IM1 §16)", () => {
  function publicSeason(base: Api): Api {
    return {
      ...base,
      getAbout: async () => ({
        ...(await base.getAbout()),
        test_season: false,
      }),
    };
  }

  async function playOnScreen(api: Api): Promise<HTMLElement> {
    const view = renderAt("/instant", api);
    fireEvent.click(await screen.findByRole("button", { name: "Get a code" }));
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "tower" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByRole("region", { name: "Instant result" });
    return view.container;
  }

  it("copies the address of the public page", async () => {
    const copied: string[] = [];
    vi.stubGlobal("navigator", {
      ...navigator,
      share: undefined,
      clipboard: {
        writeText: (text: string) => {
          copied.push(text);
          return Promise.resolve();
        },
      },
    });
    const api = publicSeason(
      makeMockApi({ today: HARNESS_TODAY, instantPendingReads: 0 }),
    );
    await playOnScreen(api);
    fireEvent.click(await screen.findByRole("button", { name: "Share" }));
    await waitFor(() => expect(copied).toHaveLength(1));
    const trial = (await api.getInstant()).trials[0];
    expect(copied[0]).toBe(
      `${window.location.origin}/t/${trial?.date}/${trial?.trial_id}`,
    );
    expect(await screen.findByText("Link copied.")).toBeDefined();
  });

  it("has no Share in a test season, where no page is public", async () => {
    const api = makeMockApi({ today: HARNESS_TODAY, instantPendingReads: 0 });
    await playOnScreen(api);
    expect(screen.queryByRole("button", { name: "Share" })).toBeNull();
  });
});
