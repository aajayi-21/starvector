import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DevApi } from "../../src/dev/api";
import { DevApiError } from "../../src/dev/api";
import { DevApp, TAB_KEY, TOKEN_KEY } from "../../src/dev/app";
import { ORIGIN_KEY } from "../../src/dev/invite-panel";
import type {
  DevDayRow,
  DevPlayerDetail,
  DevRankings,
  DevSchedule,
  DevStored,
} from "../../src/dev/types";

beforeEach(() => {
  window.localStorage.removeItem(TAB_KEY);
});

afterEach(() => {
  vi.restoreAllMocks();
});

/** Open one console tab by its visible name. */
function openTab(name: string): void {
  fireEvent.click(screen.getByRole("tab", { name }));
}

function dayRow(overrides: Partial<DevDayRow>): DevDayRow {
  return {
    day: "2026-08-12",
    status: "open",
    trial_code: "AAAAAA",
    target_id: "t".repeat(64),
    commitment: "c".repeat(64),
    submitted: true,
    sends: overrides.submitted === false ? 0 : 1,
    ...overrides,
  };
}

function scheduleFixture(overrides: Partial<DevSchedule> = {}): DevSchedule {
  return {
    closes_at_utc: "22:00",
    now: "2026-08-12T12:00:00+00:00",
    running_label: "2026-08-12",
    latest: {
      day: "2026-08-12",
      status: "open",
      closes_at: "2026-08-12T22:00:00+00:00",
    },
    paused: false,
    pause_changed_at: null,
    pause_note: "",
    lock_held: false,
    due_now: { at: "2026-08-12T12:00:00+00:00", steps: [], opens: null },
    next_run: {
      at: "2026-08-12T22:00:00+00:00",
      steps: ["close", "reveal", "open"],
      opens: "2026-08-13",
    },
    runs: [],
    ...overrides,
  };
}

function playerFixture(
  overrides: Partial<DevPlayerDetail> = {},
): DevPlayerDetail {
  return {
    player: "ade",
    display_name: "Ade",
    status: "active",
    created_at: "2026-08-12T00:00:00+00:00",
    description: "Sketches in pencil.",
    has_avatar: false,
    account_updated_at: null,
    sessions: [
      {
        id: "a".repeat(64),
        label: "Firefox on Linux",
        created_at: "2026-08-12T00:00:00+00:00",
        ends_at: "2027-02-08T00:00:00+00:00",
      },
    ],
    device_codes: [],
    sends: 1,
    ...overrides,
  };
}

function storedFor(day: string): DevStored {
  return {
    day,
    player: "ade",
    trial_id: "f".repeat(32),
    received_at: "2026-08-12T00:00:00+00:00",
    record: {
      impressions: ["tall vertical structure"],
      canvas_strokes: [
        {
          points: [
            [0.1, 0.1],
            [0.5, 0.5],
          ],
          group_id: null,
        },
      ],
      groups: [],
      relations: [],
      pasted_text: null,
    },
  };
}

function rankingsFixture(poolCount: number): DevRankings {
  return {
    trial: {
      p: 0.8712,
      decoy_count: poolCount - 5,
      beaten: 30,
      tied: 0,
      target_rank: 6,
    },
    target_position: 30,
    channel_names: ["element", "outline"],
    rankings: Array.from({ length: poolCount }, (_, index) => ({
      position: index + 1,
      image_id: `${index.toString(16).padStart(4, "0")}${"0".repeat(60)}`,
      fused: 1 - index / poolCount,
      channels: { element: 0.123456, outline: -0.654321 },
      is_target: index + 1 === 30,
    })),
    report: [
      {
        atom_id: "a1",
        atom_text: "tall vertical structure",
        element: "lighthouse tower",
        weight: 0.2984,
        similarity: 0.8123,
        rarity: 1.6412,
      },
    ],
  };
}

function makeStubApi(days: DevDayRow[]): DevApi & {
  rankingsCalls: string[];
  lifecycle: string[];
  mints: Array<[string, string]>;
  calls: string[];
} {
  const rankingsCalls: string[] = [];
  const lifecycle: string[] = [];
  const mints: Array<[string, string]> = [];
  const calls: string[] = [];
  const invite = (player: string) => ({
    player,
    display_name: player,
    token: `${player}.${"t".repeat(43)}`,
    join_path: `/join/${player}.${"t".repeat(43)}`,
  });
  return {
    rankingsCalls,
    lifecycle,
    mints,
    calls,
    getDays: () => Promise.resolve({ days }),
    getDay: (day) => {
      const row = days.find((r) => r.day === day) ?? dayRow({ day });
      return Promise.resolve({
        day,
        status: row.status,
        trial_code: row.trial_code,
        target_id: row.target_id,
        commitment: row.commitment,
        opened_at: "2026-08-11T22:00:00+00:00",
        closed_at: null,
        revealed_at: null,
        closes_at: "2026-08-12T22:00:00+00:00",
        scoring_config_hash: "9".repeat(64),
        preparation_version_id: "prep",
        credit: null,
        sends: row.submitted
          ? [
              {
                player: "ade",
                display_name: "Ade",
                received_at: "2026-08-12T00:00:00+00:00",
                trial_id: "f".repeat(32),
                trial: null,
              },
            ]
          : [],
      });
    },
    getSubmission: (day) => {
      const row = days.find((r) => r.day === day);
      if (row === undefined || !row.submitted) {
        return Promise.reject(new DevApiError(404, "no submission"));
      }
      return Promise.resolve(storedFor(day));
    },
    getRankings: (day) => {
      rankingsCalls.push(day);
      return Promise.resolve(rankingsFixture(40));
    },
    getPlayers: () =>
      Promise.resolve({
        players: [
          {
            player: "ade",
            display_name: "Ade",
            status: "active" as const,
            created_at: "2026-08-12T00:00:00+00:00",
            devices: 1,
            last_signed_in: "2026-08-12T00:00:00+00:00",
            device_codes: 0,
            sends: 1,
          },
        ],
      }),
    getHistory: (player) =>
      Promise.resolve({
        player,
        days: days.map((row) => ({
          day: row.day,
          status: row.status,
          trial_code: row.trial_code,
          target_id: row.target_id,
          submitted: row.submitted,
          trial: null,
        })),
      }),
    postOpen: () => {
      lifecycle.push("open");
      return Promise.resolve({});
    },
    postClose: () => {
      lifecycle.push("close");
      return Promise.resolve({});
    },
    postReveal: () => {
      lifecycle.push("reveal");
      return Promise.resolve({});
    },
    mintPlayer: (player, displayName) => {
      mints.push([player, displayName]);
      return Promise.resolve({
        player,
        display_name: displayName,
        token: `${player}.${"s".repeat(43)}`,
        join_path: `/join/${player}.${"s".repeat(43)}`,
      });
    },
    imageUrl: (imageId) => `stub:/image/${imageId}`,
    getAbout: () =>
      Promise.resolve({
        test_season: true,
        photo_count: 40,
        closes_at_utc: "22:00",
      }),
    getSchedule: () => Promise.resolve(scheduleFixture()),
    setPause: (paused, note) => {
      calls.push(`pause ${paused} ${note}`);
      return Promise.resolve(
        scheduleFixture({
          paused,
          pause_note: note,
          pause_changed_at: paused ? "2026-08-12T12:00:00+00:00" : null,
        }),
      );
    },
    runRollover: () => {
      calls.push("run");
      return Promise.resolve({
        run: {
          started_at: "2026-08-12T22:30:00+00:00",
          finished_at: "2026-08-12T22:30:05+00:00",
          source: "console" as const,
          outcome: "moved" as const,
          steps: ["close", "reveal", "open"] as Array<
            "open" | "close" | "reveal"
          >,
          detail: "rollover: close {}",
        },
        schedule: scheduleFixture(),
      });
    },
    getPlayer: (player) => {
      calls.push(`player ${player}`);
      return Promise.resolve(playerFixture({ player }));
    },
    getAvatar: () => Promise.resolve(null),
    rotatePlayer: (player) => {
      calls.push(`rotate ${player}`);
      return Promise.resolve(invite(player));
    },
    restorePlayer: (player) => {
      calls.push(`restore ${player}`);
      return Promise.resolve(invite(player));
    },
    revokePlayer: (player) => {
      calls.push(`revoke ${player}`);
      return Promise.resolve({ player, status: "revoked" });
    },
    signOutPlayer: (player) => {
      calls.push(`signout ${player}`);
      return Promise.resolve({ player, ended: 1 });
    },
    endSession: (player, id) => {
      calls.push(`end ${player} ${id.slice(0, 4)}`);
      return Promise.resolve({ player, ended: 1 });
    },
    issueDeviceCode: (player) => {
      calls.push(`code ${player}`);
      return Promise.resolve({
        player,
        code: "ABCDEFGH",
        display: "ABCD-EFGH",
        expires_at: "2026-08-12T12:10:00+00:00",
      });
    },
    prune: () => {
      calls.push("prune");
      return Promise.resolve({ sessions: 2, device_codes: 1 });
    },
    getIndex: () =>
      Promise.resolve({
        path: "data/index/results-v1.sqlite",
        exists: false,
        schema_version: 1,
        built_at: null,
        current: false,
        problem: null,
        tables: [],
      }),
    buildIndex: () => {
      calls.push("build");
      return Promise.resolve({
        path: "data/index/results-v1.sqlite",
        exists: true,
        schema_version: 1,
        built_at: "2026-08-12T12:00:00+00:00",
        current: true,
        problem: null,
        tables: [
          {
            name: "trials",
            rows: 3,
            columns: ["day", "player", "p"],
            view: false,
          },
          {
            name: "revealed_trials",
            rows: 2,
            columns: ["day", "player", "p"],
            view: true,
          },
        ],
      });
    },
    verifyIndex: () => {
      calls.push("verify");
      return Promise.resolve({ agrees: true, problems: [] });
    },
    queryIndex: (sql) => {
      calls.push(`query ${sql.slice(0, 20)}`);
      return Promise.resolve({
        columns: ["player", "p", "note"],
        rows: [
          ["ade", 0.75, null],
          ["bru", 0.5, "a, b"],
        ],
        truncated: false,
        elapsed_ms: 3,
      });
    },
  };
}

describe("the operator console", () => {
  it("shows the right control for each latest-day status", async () => {
    for (const [status, label] of [
      ["open", "Close the day (scores now)"],
      ["closing", "Finish closing (a close stopped part way)"],
      ["closed", "Reveal"],
      ["revealed", "Open the next day"],
    ] as const) {
      const api = makeStubApi([dayRow({ status, submitted: false })]);
      const view = render(<DevApp api={api} />);
      expect(await screen.findByText(label)).toBeDefined();
      view.unmount();
    }
  });

  it("offers no open while the latest day is not revealed (spec BR1 §3)", async () => {
    for (const [status, control] of [
      ["open", "Close the day (scores now)"],
      ["closing", "Finish closing (a close stopped part way)"],
      ["closed", "Reveal"],
    ] as const) {
      const api = makeStubApi([dayRow({ status, submitted: false })]);
      const view = render(<DevApp api={api} />);
      await screen.findByText(control);
      expect(screen.queryByText("Open the next day")).toBeNull();
      view.unmount();
    }
  });

  it("moves the latest day alone: a browsed earlier day has no controls", async () => {
    const api = makeStubApi([
      dayRow({ day: "2026-08-13", status: "open", submitted: false }),
      dayRow({ day: "2026-08-12", status: "revealed", submitted: false }),
    ]);
    render(<DevApp api={api} />);
    await screen.findByText("Close the day (scores now)");
    fireEvent.change(screen.getByLabelText("stored day"), {
      target: { value: "2026-08-12" },
    });
    await waitFor(() => {
      expect(screen.queryByText("Open the next day")).toBeNull();
      expect(screen.queryByText("Close the day (scores now)")).toBeNull();
      expect(screen.queryByText("Reveal")).toBeNull();
    });
  });

  it("asks for confirmation before close, and posts on accept", async () => {
    const api = makeStubApi([dayRow({ status: "open", submitted: false })]);
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    render(<DevApp api={api} />);
    const close = await screen.findByText("Close the day (scores now)");
    fireEvent.click(close);
    expect(api.lifecycle).toEqual([]);
    fireEvent.click(close);
    await waitFor(() => expect(api.lifecycle).toEqual(["close"]));
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("hides the target by default and clears it on a day switch", async () => {
    const api = makeStubApi([
      dayRow({ day: "2026-08-13", submitted: false }),
      dayRow({ day: "2026-08-12", status: "revealed", submitted: false }),
    ]);
    render(<DevApp api={api} />);
    const toggle = await screen.findByText("Show the target");
    expect(screen.queryByAltText(/target for/)).toBeNull();
    fireEvent.click(toggle);
    expect(await screen.findByAltText("target for 2026-08-13")).toBeDefined();
    fireEvent.change(screen.getByLabelText("stored day"), {
      target: { value: "2026-08-12" },
    });
    await waitFor(() => {
      expect(screen.queryByAltText(/target for/)).toBeNull();
    });
    expect(screen.getByText("Show the target")).toBeDefined();
  });

  it("loads rankings itself when closed, by hand while open", async () => {
    const closed = makeStubApi([dayRow({ status: "closed" })]);
    const view = render(<DevApp api={closed} />);
    await waitFor(() => expect(closed.rankingsCalls).toEqual(["2026-08-12"]));
    expect(
      await screen.findByText(/target at position 30 of 40/),
    ).toBeDefined();
    view.unmount();

    const open = makeStubApi([dayRow({ status: "open" })]);
    render(<DevApp api={open} />);
    const preview = await screen.findByText("Score and rank the submission");
    expect(open.rankingsCalls).toEqual([]);
    fireEvent.click(preview);
    await waitFor(() => expect(open.rankingsCalls).toEqual(["2026-08-12"]));
  });

  it("renders the report decimals and the top-25 slice with the target", async () => {
    const api = makeStubApi([dayRow({ status: "revealed" })]);
    render(<DevApp api={api} />);
    await screen.findByText(/target at position 30 of 40/);
    expect(screen.getByText("0.298")).toBeDefined();
    expect(screen.getByText("0.812")).toBeDefined();
    expect(screen.getByText("1.64")).toBeDefined();
    // 25 sliced rows plus the target row from position 30.
    expect(screen.getByText(/← target/)).toBeDefined();
    const rows = document.querySelectorAll(".dev-rankings tbody tr");
    expect(rows).toHaveLength(26);
    fireEvent.click(screen.getByText("Show the full ranking"));
    await waitFor(() => {
      expect(document.querySelectorAll(".dev-rankings tbody tr")).toHaveLength(
        40,
      );
    });
  });
});

describe("the console's async discipline", () => {
  it("drops a response from a day the operator left", async () => {
    let releaseFirst: (value: DevRankings) => void = () => undefined;
    const slow = new Promise<DevRankings>((resolve) => {
      releaseFirst = resolve;
    });
    const base = makeStubApi([
      dayRow({ day: "2026-08-13", status: "revealed" }),
      dayRow({ day: "2026-08-12", status: "revealed" }),
    ]);
    const api: DevApi = {
      ...base,
      getRankings: (day) => {
        base.rankingsCalls.push(day);
        return day === "2026-08-13"
          ? slow
          : Promise.resolve(rankingsFixture(8));
      },
    };
    render(<DevApp api={api} />);
    await screen.findByLabelText("stored day");
    fireEvent.change(screen.getByLabelText("stored day"), {
      target: { value: "2026-08-12" },
    });
    await waitFor(() => expect(screen.getByText(/of 8 \(rank/)).toBeDefined());
    // The abandoned day's answer lands late and must be ignored.
    releaseFirst(rankingsFixture(40));
    await waitFor(() => expect(screen.getByText(/of 8 \(rank/)).toBeDefined());
    expect(screen.queryByText(/of 40 \(rank/)).toBeNull();
  });

  it("offers no control before the day listing lands", async () => {
    let release: (value: { days: DevDayRow[] }) => void = () => undefined;
    const gate = new Promise<{ days: DevDayRow[] }>((resolve) => {
      release = resolve;
    });
    const base = makeStubApi([dayRow({ status: "revealed" })]);
    const api: DevApi = { ...base, getDays: () => gate };
    render(<DevApp api={api} />);
    expect(screen.queryByText("Open the next day")).toBeNull();
    release({ days: [dayRow({ status: "revealed" })] });
    expect(await screen.findByText("Open the next day")).toBeDefined();
  });

  it("keeps the operator token across visits", async () => {
    window.localStorage.removeItem(TOKEN_KEY);
    const api = makeStubApi([dayRow({ status: "revealed" })]);
    const first = render(<DevApp api={api} />);
    const field = await screen.findByLabelText("operator token");
    // A password field: the token is a credential, not a setting.
    expect(field.getAttribute("type")).toBe("password");
    fireEvent.change(field, { target: { value: "an-operator-token" } });
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe("an-operator-token");
    first.unmount();

    render(<DevApp api={api} />);
    const again = await screen.findByLabelText("operator token");
    expect((again as HTMLInputElement).value).toBe("an-operator-token");
    window.localStorage.removeItem(TOKEN_KEY);
  });

  it("names both causes of a refused dev read", async () => {
    // The server answers a refused operator check on a dev read
    // with the same 404 it gives with no --dev flag, on purpose: a
    // 401 there would announce that dev mode is on. The console
    // only ever runs against a dev server, thus it can say both
    // causes without opening that oracle on the wire.
    const base = makeStubApi([]);
    const api: DevApi = {
      ...base,
      getDays: () => Promise.reject(new DevApiError(404, "not found")),
    };
    render(<DevApp api={api} />);
    const note = await screen.findByText(/start the server with --dev/);
    expect(note.textContent).toContain("operator token is missing or wrong");
  });

  it("mints an invite and prints it one time", async () => {
    window.localStorage.removeItem(ORIGIN_KEY);
    const api = makeStubApi([dayRow({ status: "revealed" })]);
    render(<DevApp api={api} />);
    openTab("Players");
    const name = await screen.findByLabelText("player name");
    fireEvent.change(name, { target: { value: "bru" } });
    fireEvent.change(screen.getByLabelText("display name"), {
      target: { value: "Bru Lin" },
    });
    fireEvent.change(screen.getByLabelText("invite origin"), {
      target: { value: "https://game.example.com" },
    });
    fireEvent.click(screen.getByText("Mint the invite"));

    await waitFor(() => expect(api.mints).toEqual([["bru", "Bru Lin"]]));
    // The origin is the operator's, not this console's address: the
    // console is reached through a tunnel at localhost while the
    // invite has to name the public site.
    const url = await screen.findByTestId("invite-url");
    expect(url.textContent).toBe(
      `https://game.example.com/join/bru.${"s".repeat(43)}`,
    );
    expect(screen.getByText(/one time the invite prints/)).toBeDefined();
    // A minted token is never persisted: the store keeps its digest
    // alone, thus a lost invite wants a rotate and not a lookup.
    const kept = Object.values(window.localStorage);
    expect(kept.join(" ")).not.toContain("s".repeat(43));
    window.localStorage.removeItem(ORIGIN_KEY);
  });

  it("defaults the display name to the player name", async () => {
    const api = makeStubApi([dayRow({ status: "revealed" })]);
    render(<DevApp api={api} />);
    fireEvent.change(await screen.findByLabelText("player name"), {
      target: { value: "cyd" },
    });
    fireEvent.click(screen.getByText("Mint the invite"));
    await waitFor(() => expect(api.mints).toEqual([["cyd", "cyd"]]));
  });

  it("refuses to mint with no player name", async () => {
    const api = makeStubApi([dayRow({ status: "revealed" })]);
    render(<DevApp api={api} />);
    const button = await screen.findByText("Mint the invite");
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(api.mints).toEqual([]);
  });

  it("says why a mint was refused", async () => {
    const base = makeStubApi([dayRow({ status: "revealed" })]);
    const api: DevApi = {
      ...base,
      mintPlayer: () =>
        Promise.reject(new DevApiError(409, "player 'ade' is stored")),
    };
    render(<DevApp api={api} />);
    fireEvent.change(await screen.findByLabelText("player name"), {
      target: { value: "ade" },
    });
    fireEvent.click(screen.getByText("Mint the invite"));
    expect(await screen.findByText("player 'ade' is stored")).toBeDefined();
    expect(screen.queryByTestId("invite-url")).toBeNull();
  });

  it("shows a failed submission read instead of nothing-sent", async () => {
    const base = makeStubApi([dayRow({ status: "open" })]);
    const api: DevApi = {
      ...base,
      getSubmission: () =>
        Promise.reject(new DevApiError(500, "the server did not answer")),
    };
    render(<DevApp api={api} />);
    expect(await screen.findByText("the server did not answer")).toBeDefined();
    expect(screen.queryByText("nothing sent this day")).toBeNull();
  });

  // Spec A1 §5: the roster is the second axis — click a player,
  // read their history, open a stored day.
  it("opens a player's history from the roster and drills to a day", async () => {
    const api = makeStubApi([dayRow({ status: "revealed" })]);
    const view = render(<DevApp api={api} />);
    openTab("Players");
    const panel = () => {
      const found = view.container.querySelector("#roster-panel");
      if (found === null) {
        throw new Error("no roster panel");
      }
      return found as HTMLElement;
    };
    expect(await within(panel()).findByText("Players")).toBeDefined();
    fireEvent.click(
      await within(panel()).findByRole("button", { name: "ade" }),
    );
    expect(await within(panel()).findByText("ade — history")).toBeDefined();
    fireEvent.click(
      await within(panel()).findByRole("button", { name: "2026-08-12" }),
    );
    expect(await within(panel()).findByText("Stored submission")).toBeDefined();
    fireEvent.click(
      await within(panel()).findByText("Score and rank the submission"),
    );
    await waitFor(() => expect(api.rankingsCalls).toContain("2026-08-12"));
  });

  it("reloads the roster when the operator token field blurs", async () => {
    // A roster that failed before the paste recovers with the day
    // browser, wanting no page reload (the review of 2026-08-21).
    const base = makeStubApi([dayRow({ status: "revealed" })]);
    let calls = 0;
    const api: DevApi = {
      ...base,
      getPlayers: () => {
        calls += 1;
        if (calls === 1) {
          return Promise.reject(new DevApiError(404, "not found"));
        }
        return base.getPlayers();
      },
    };
    const view = render(<DevApp api={api} />);
    const panel = () => {
      const found = view.container.querySelector("#roster-panel");
      if (found === null) {
        throw new Error("no roster panel");
      }
      return found as HTMLElement;
    };
    await waitFor(() =>
      expect(within(panel()).getByText(/start the server with/)).toBeDefined(),
    );
    openTab("Players");
    fireEvent.blur(screen.getByLabelText("operator token"));
    await waitFor(() =>
      expect(
        within(panel()).getByRole("button", { name: "ade" }),
      ).toBeDefined(),
    );
  });

  it("reads the roster refusal as no dev flag or a missing token", async () => {
    const base = makeStubApi([dayRow({ status: "revealed" })]);
    const api: DevApi = {
      ...base,
      getPlayers: () => Promise.reject(new DevApiError(404, "not found")),
    };
    const view = render(<DevApp api={api} />);
    const panel = () => {
      const found = view.container.querySelector("#roster-panel");
      if (found === null) {
        throw new Error("no roster panel");
      }
      return found as HTMLElement;
    };
    await waitFor(() =>
      expect(within(panel()).getByText(/start the server with/)).toBeDefined(),
    );
  });
});

// ── spec BR1 §7: the console's four tabs ────────────────────────

describe("the console tabs", () => {
  it("opens on Days, moves with a click or the arrow keys, and remembers", async () => {
    const api = makeStubApi([dayRow({ status: "open" })]);
    const first = render(<DevApp api={api} />);
    const days = await screen.findByRole("tab", { name: "Days" });
    expect(days.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(days, { key: "ArrowRight" });
    expect(
      screen
        .getByRole("tab", { name: "Automatic days" })
        .getAttribute("aria-selected"),
    ).toBe("true");
    openTab("Results database");
    expect(window.localStorage.getItem(TAB_KEY)).toBe("index");
    first.unmount();

    render(<DevApp api={api} />);
    expect(
      (
        await screen.findByRole("tab", { name: "Results database" })
      ).getAttribute("aria-selected"),
    ).toBe("true");
  });

  it("shows the season facts in the header", async () => {
    render(<DevApp api={makeStubApi([dayRow({})])} />);
    expect(
      await screen.findByText("Test season · 40 photos · days close 22:00 UTC"),
    ).toBeDefined();
  });
});

describe("the Days tab", () => {
  it("lists each send and opens the one the operator picks", async () => {
    const base = makeStubApi([dayRow({ status: "open" })]);
    const opened: string[] = [];
    const api: DevApi = {
      ...base,
      getDay: async (day) => ({
        ...(await base.getDay(day)),
        sends: [
          {
            player: "ade",
            display_name: "Ade",
            received_at: "2026-08-12T01:00:00+00:00",
            trial_id: "f".repeat(32),
            trial: null,
          },
          {
            player: "bru",
            display_name: "Bru Lin",
            received_at: "2026-08-12T02:00:00+00:00",
            trial_id: "e".repeat(32),
            trial: null,
          },
        ],
      }),
      getSubmission: (day, player) => {
        opened.push(player ?? "(configured)");
        return base.getSubmission(day, player);
      },
    };
    render(<DevApp api={api} />);
    await screen.findByText("Bru Lin");
    await waitFor(() => expect(opened).toEqual(["ade"]));
    fireEvent.click(screen.getByText("Bru Lin"));
    await waitFor(() => expect(opened).toEqual(["ade", "bru"]));
  });

  it("says nobody sent when the day holds no send", async () => {
    render(<DevApp api={makeStubApi([dayRow({ submitted: false })])} />);
    expect(await screen.findByText("Nobody sent this day.")).toBeDefined();
  });
});

describe("the Automatic days tab", () => {
  it("says the days are off with no rollover hour", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi = {
      ...base,
      getSchedule: () =>
        Promise.resolve(
          scheduleFixture({
            closes_at_utc: null,
            due_now: null,
            next_run: null,
          }),
        ),
    };
    render(<DevApp api={api} />);
    openTab("Automatic days");
    expect(await screen.findByText("Automatic days are off")).toBeDefined();
    expect(screen.queryByText("Do what is due now")).toBeNull();
  });

  it("names the next run's steps in words", async () => {
    render(<DevApp api={makeStubApi([dayRow({})])} />);
    openTab("Automatic days");
    expect(await screen.findByText("Automatic days are on")).toBeDefined();
    expect(screen.getByText("Close 2026-08-12 and score it")).toBeDefined();
    expect(screen.getByText("Reveal 2026-08-12")).toBeDefined();
    expect(screen.getByText("Open 2026-08-13")).toBeDefined();
    expect(screen.getByText("Nothing is due now.")).toBeDefined();
    const run = screen.getByText("Do what is due now") as HTMLButtonElement;
    expect(run.disabled).toBe(true);
  });

  it("pauses with a note and resumes", async () => {
    const api = makeStubApi([dayRow({})]);
    render(<DevApp api={api} />);
    openTab("Automatic days");
    fireEvent.change(await screen.findByLabelText("pause note"), {
      target: { value: "holiday" },
    });
    fireEvent.click(screen.getByText("Pause automatic days"));
    expect(await screen.findByText("Automatic days are paused")).toBeDefined();
    expect(screen.getByText(/“holiday”/)).toBeDefined();
    fireEvent.click(screen.getByText("Resume automatic days"));
    expect(await screen.findByText("Automatic days are on")).toBeDefined();
    expect(api.calls).toEqual(["pause true holiday", "pause false "]);
  });

  it("does what is due after a confirmation, and every tab reads again", async () => {
    const base = makeStubApi([dayRow({ status: "closed" })]);
    let dayReads = 0;
    const due = scheduleFixture({
      latest: { day: "2026-08-12", status: "closed", closes_at: null },
      due_now: {
        at: "2026-08-12T23:00:00+00:00",
        steps: ["reveal", "open"],
        opens: "2026-08-13",
      },
    });
    const api: DevApi & { calls: string[] } = {
      ...base,
      getDays: () => {
        dayReads += 1;
        return base.getDays();
      },
      getSchedule: () => Promise.resolve(due),
    };
    const confirm = vi
      .spyOn(window, "confirm")
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true);
    render(<DevApp api={api} />);
    openTab("Automatic days");
    const button = (await screen.findByText(
      "Do what is due now",
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(api.calls).toEqual([]);
    expect(confirm).toHaveBeenLastCalledWith(
      "Reveal 2026-08-12, then Open 2026-08-13?",
    );
    const before = dayReads;
    fireEvent.click(button);
    await waitFor(() => expect(api.calls).toEqual(["run"]));
    expect(await screen.findByText("This run · moved")).toBeDefined();
    await waitFor(() => expect(dayReads).toBeGreaterThan(before));
  });

  it("holds the button while a rollover holds the lock", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi = {
      ...base,
      getSchedule: () =>
        Promise.resolve(
          scheduleFixture({
            lock_held: true,
            due_now: {
              at: "2026-08-12T23:00:00+00:00",
              steps: ["close", "reveal", "open"],
              opens: "2026-08-13",
            },
          }),
        ),
    };
    render(<DevApp api={api} />);
    openTab("Automatic days");
    const button = (await screen.findByText(
      "Do what is due now",
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(screen.getByText(/A rollover is running now/)).toBeDefined();
  });

  it("lists the recent runs with their source and outcome", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi = {
      ...base,
      getSchedule: () =>
        Promise.resolve(
          scheduleFixture({
            runs: [
              {
                started_at: "2026-08-11T22:00:00+00:00",
                finished_at: "2026-08-11T22:01:00+00:00",
                source: "timer",
                outcome: "failed",
                steps: ["close"],
                detail: "rollover failed: reveal did not complete",
              },
            ],
          }),
        ),
    };
    render(<DevApp api={api} />);
    openTab("Automatic days");
    expect(await screen.findByText("Timer")).toBeDefined();
    expect(screen.getByText("failed")).toBeDefined();
    expect(
      screen.getByText("rollover failed: reveal did not complete"),
    ).toBeDefined();
  });
});

describe("the Players tab", () => {
  async function openAde(api: DevApi): Promise<void> {
    render(<DevApp api={api} />);
    openTab("Players");
    fireEvent.click(await screen.findByRole("button", { name: "ade" }));
    await screen.findByText("Firefox on Linux");
  }

  it("shows the account, the devices, and the counts", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    expect(screen.getByText("Sketches in pencil.")).toBeDefined();
    expect(screen.getByText("Devices signed in · 1")).toBeDefined();
    expect(api.calls).toContain("player ade");
  });

  it("signs one device out", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(api.calls).toContain("end ade aaaa"));
    expect(
      await screen.findByText("Firefox on Linux is signed out."),
    ).toBeDefined();
  });

  it("prints a new invite address one time, with the invite origin", async () => {
    window.localStorage.setItem(ORIGIN_KEY, "https://game.example.com/");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    fireEvent.click(screen.getByText("New invite address"));
    const url = await screen.findByTestId("account-invite-url");
    expect(url.textContent).toBe(
      `https://game.example.com/join/ade.${"t".repeat(43)}`,
    );
    expect(api.calls).toContain("rotate ade");
    const kept = Object.values(window.localStorage);
    expect(kept.join(" ")).not.toContain("t".repeat(43));
    window.localStorage.removeItem(ORIGIN_KEY);
  });

  it("prints a device code for a player with no signed-in device", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    fireEvent.click(screen.getByText("Device code"));
    expect((await screen.findByTestId("account-device-code")).textContent).toBe(
      "ABCD-EFGH",
    );
  });

  it("asks before a revoke, and offers a restore for a revoked player", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    const base = makeStubApi([dayRow({})]);
    let revoked = false;
    const api: DevApi & { calls: string[] } = {
      ...base,
      getPlayer: async (player) =>
        revoked
          ? playerFixture({ player, status: "revoked", sessions: [] })
          : base.getPlayer(player),
      revokePlayer: async (player) => {
        revoked = true;
        return base.revokePlayer(player);
      },
    };
    await openAde(api);
    fireEvent.click(screen.getByText("Revoke access"));
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(api.calls).not.toContain("revoke ade");
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByText("Revoke access"));
    expect(await screen.findByText("Restore access")).toBeDefined();
    expect(api.calls).toContain("revoke ade");
    expect(screen.queryByText("New invite address")).toBeNull();
  });

  it("removes expired sign-ins and says how many", async () => {
    const api = makeStubApi([dayRow({})]);
    render(<DevApp api={api} />);
    openTab("Players");
    fireEvent.click(await screen.findByText("Remove expired sign-ins"));
    expect(
      await screen.findByText(
        "Removed 2 expired sign-ins and 1 expired device code.",
      ),
    ).toBeDefined();
  });
});

describe("the Results database tab", () => {
  it("builds, checks, and counts the tables", async () => {
    const api = makeStubApi([dayRow({})]);
    render(<DevApp api={api} />);
    openTab("Results database");
    expect(await screen.findByText("Not built yet")).toBeDefined();
    fireEvent.click(screen.getByText("Build again from the store"));
    expect(await screen.findByText("Up to date with the store")).toBeDefined();
    expect(screen.getByText("revealed_trials")).toBeDefined();
    fireEvent.click(screen.getByText("Check against the store"));
    expect(
      await screen.findByText(
        "The index agrees with the store, table by table.",
      ),
    ).toBeDefined();
  });

  it("runs a query, shows NULL as NULL, and fills an example", async () => {
    const api = makeStubApi([dayRow({})]);
    render(<DevApp api={api} />);
    openTab("Results database");
    const box = (await screen.findByLabelText(
      "SQL query",
    )) as HTMLTextAreaElement;
    fireEvent.click(screen.getByText("Players and accounts"));
    expect(box.value).toContain("FROM players AS p");
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    expect(await screen.findByText("bru")).toBeDefined();
    expect(screen.getByText("NULL").className).toBe("dev-null");
    expect(screen.getByText(/2 rows/)).toBeDefined();
  });

  it("shows the server's refusal of a query", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi = {
      ...base,
      queryIndex: () => Promise.reject(new DevApiError(400, "not authorized")),
    };
    render(<DevApp api={api} />);
    openTab("Results database");
    fireEvent.click(await screen.findByText("Run query"));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "not authorized",
    );
  });
});
