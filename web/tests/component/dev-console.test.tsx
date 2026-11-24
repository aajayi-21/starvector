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
    has_password: true,
    operator_code: null,
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

/** The recovery codes the stub prints: test values, no account's. */
const OPERATOR_CODE = "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2";
const RESTORE_CODE = "2345-6789-ABCD-EFGH-JKMN-PQRS";

function makeStubApi(days: DevDayRow[]): DevApi & {
  rankingsCalls: string[];
  lifecycle: string[];
  calls: string[];
} {
  const rankingsCalls: string[] = [];
  const lifecycle: string[] = [];
  const calls: string[] = [];
  return {
    rankingsCalls,
    lifecycle,
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
      return Promise.resolve({ day: "2026-08-12" });
    },
    closeDay: (day) => {
      lifecycle.push(`close ${day}`);
      return Promise.resolve({ trial_rows: 1 });
    },
    revealDay: (day) => {
      lifecycle.push(`reveal ${day}`);
      return Promise.resolve({ day });
    },
    imageUrl: (imageId) => `stub:/image/${imageId}`,
    getAbout: () =>
      Promise.resolve({
        test_season: true,
        photo_count: 40,
        instant: "off",
        closes_at_utc: "22:00",
        public_data_url: null,
        pick_protocol: "commit-v1",
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
    issueRecoveryCode: (player) => {
      calls.push(`recovery-code ${player}`);
      return Promise.resolve({
        player,
        recovery_code: OPERATOR_CODE,
        usable_at: "2026-08-13T12:00:00+00:00",
      });
    },
    restorePlayer: (player) => {
      calls.push(`restore ${player}`);
      return Promise.resolve({
        player,
        status: "active" as const,
        recovery_code: RESTORE_CODE,
        usable_at: "2026-08-13T12:00:00+00:00",
      });
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
    prune: () => {
      calls.push("prune");
      return Promise.resolve({ sessions: 2, device_codes: 1 });
    },
    setDescription: (player, description) => {
      calls.push(`description ${player} ${description}`);
      return Promise.resolve({ player, description });
    },
    setAvatar: (player) => {
      calls.push(`avatar ${player}`);
      return Promise.resolve({ player, avatar_hash: "c".repeat(64) });
    },
    removeAvatar: (player) => {
      calls.push(`remove-avatar ${player}`);
      return Promise.resolve({ player, avatar_hash: null });
    },
    getDeletionPreview: (player) => {
      calls.push(`preview ${player}`);
      return Promise.resolve({
        player,
        status: "active" as const,
        days_played: 3,
        first_day: "2026-08-10",
        last_day: "2026-08-12",
        sessions: 1,
        has_password: true,
        identifier: null,
        removes: ["the player record", "the account and the avatar"],
        keeps: ["each send and trial result, with an anonymous name"],
      });
    },
    deletePlayer: (player, confirm) => {
      calls.push(`delete ${player} ${confirm}`);
      return Promise.resolve({
        player,
        deleted: true as const,
        identifier: "anon-0123456789abcdef",
      });
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
      ["open", "Close the day"],
      ["closing", "Finish closing"],
      ["closed", "Reveal"],
      ["revealed", "Open the next day"],
    ] as const) {
      const api = makeStubApi([dayRow({ status, submitted: false })]);
      const view = render(<DevApp api={api} />);
      expect(await screen.findByRole("button", { name: label })).toBeDefined();
      view.unmount();
    }
  });

  it("offers no open while the latest day is not revealed (spec BR1 §3)", async () => {
    for (const [status, control] of [
      ["open", "Close the day"],
      ["closing", "Finish closing"],
      ["closed", "Reveal"],
    ] as const) {
      const api = makeStubApi([dayRow({ status, submitted: false })]);
      const view = render(<DevApp api={api} />);
      await screen.findByRole("button", { name: control });
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
    await screen.findByText("Close the day");
    fireEvent.change(screen.getByLabelText("stored day"), {
      target: { value: "2026-08-12" },
    });
    await waitFor(() => {
      expect(screen.queryByText("Open the next day")).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Close the day" }),
      ).toBeNull();
      expect(screen.queryByRole("button", { name: "Reveal" })).toBeNull();
    });
    // A day that is done says so, and the note names the latest day.
    expect(screen.getByText("Nothing is due for this day")).toBeDefined();
    expect(screen.getByText(/behind the latest one/)).toBeDefined();
  });

  it("asks in the page before close, and posts on yes", async () => {
    const api = makeStubApi([dayRow({ status: "open", submitted: false })]);
    const native = vi.spyOn(window, "confirm");
    render(<DevApp api={api} />);
    fireEvent.click(await screen.findByText("Close the day"));
    expect(screen.getByText(/Close 2026-08-12\? New sends stop/)).toBeDefined();
    fireEvent.click(screen.getByText("Cancel"));
    expect(api.lifecycle).toEqual([]);
    fireEvent.click(screen.getByText("Close the day"));
    fireEvent.click(screen.getByText("Yes, close and score"));
    await waitFor(() => expect(api.lifecycle).toEqual(["close"]));
    // No browser dialog: a blocked one answers "no" with no sign.
    expect(native).not.toHaveBeenCalled();
  });

  it("hides the target by default and clears it on a day switch", async () => {
    const api = makeStubApi([
      dayRow({ day: "2026-08-13", submitted: false }),
      dayRow({ day: "2026-08-12", status: "revealed", submitted: false }),
    ]);
    render(<DevApp api={api} />);
    const toggle = await screen.findByText("Show the day's photo");
    expect(screen.queryByAltText(/target for/)).toBeNull();
    fireEvent.click(toggle);
    expect(await screen.findByAltText("target for 2026-08-13")).toBeDefined();
    fireEvent.change(screen.getByLabelText("stored day"), {
      target: { value: "2026-08-12" },
    });
    await waitFor(() => {
      expect(screen.queryByAltText(/target for/)).toBeNull();
    });
    expect(screen.getByText("Show the day's photo")).toBeDefined();
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
    // An open day: the first click asks, because the answer shows the
    // target (spec PL1 §8). Cancel stays blind, and only a yes scores.
    expect(await screen.findByText(/ends a blind run/)).toBeDefined();
    expect(open.rankingsCalls).toEqual([]);
    fireEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByText(/ends a blind run/)).toBeNull();
    expect(open.rankingsCalls).toEqual([]);
    fireEvent.click(screen.getByText("Score and rank the submission"));
    fireEvent.click(await screen.findByText("Yes, show the target"));
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
    // The server accepts the listing, thus the field waits behind the
    // quiet control in the header.
    fireEvent.click(await screen.findByText("Change token"));
    const field = screen.getByLabelText("operator token");
    // A password field: the token is a credential, not a setting.
    expect(field.getAttribute("type")).toBe("password");
    fireEvent.change(field, { target: { value: "an-operator-token" } });
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe("an-operator-token");
    first.unmount();

    render(<DevApp api={api} />);
    fireEvent.click(await screen.findByText("Change token"));
    const again = screen.getByLabelText("operator token");
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
    const card = await screen.findByTestId("console-locked");
    expect(card.textContent).toContain("Check the token");
    expect(card.textContent).toContain("start the server with --dev");
  });

  it("makes no account and no invite (spec A2 §10.1)", async () => {
    // A player makes their own account, thus the console has no form
    // that makes one.
    render(<DevApp api={makeStubApi([dayRow({ status: "revealed" })])} />);
    openTab("Players");
    await screen.findByRole("button", { name: "Manage ade" });
    expect(screen.queryByLabelText("Player name")).toBeNull();
    expect(screen.queryByText(/invite/i)).toBeNull();
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
    fireEvent.click(screen.getByText("Change token"));
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
    render(<DevApp api={api} />);
    openTab("Automatic days");
    const button = (await screen.findByText(
      "Do what is due now",
    )) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    expect(api.calls).toEqual([]);
    expect(
      screen.getByText("Reveal 2026-08-12, then Open 2026-08-13 — now?"),
    ).toBeDefined();
    fireEvent.click(screen.getByText("Cancel"));
    expect(api.calls).toEqual([]);
    const before = dayReads;
    fireEvent.click(screen.getByText("Do what is due now"));
    fireEvent.click(screen.getByText("Yes, do it now"));
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
    expect(screen.getByText("Failed")).toBeDefined();
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
    expect(
      screen.getByText("Sketches in pencil.", { selector: "p" }),
    ).toBeDefined();
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

  it("prints the operator's recovery code one time, with its hold", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    fireEvent.click(screen.getByRole("button", { name: "Recovery code" }));
    // The question names the hold and the notice before the code is made.
    expect(screen.getByText(/works only after 24 hours/)).toBeDefined();
    expect(api.calls).not.toContain("recovery-code ade");
    fireEvent.click(screen.getByText("Yes, make a recovery code"));
    const code = await screen.findByTestId("account-recovery-code");
    expect(code.textContent).toBe(OPERATOR_CODE);
    expect(api.calls).toContain("recovery-code ade");
    // The time the code starts to work, and the notice on the devices.
    expect(
      screen.getByText("It works only from 2026-08-13 12:00 UTC."),
    ).toBeDefined();
    expect(
      screen.getByText(/shows a notice with a\s+“Stop this” control/),
    ).toBeDefined();
    expect(screen.getByText(/This is the one time it prints/)).toBeDefined();
    // A printed code is never persisted: the store keeps its digest.
    const kept = Object.values(window.localStorage);
    expect(kept.join(" ")).not.toContain(OPERATOR_CODE);
  });

  it("has no invite control and no device-code control", async () => {
    // Spec A2 §10.1 and decision D13: the recovery code, with its
    // hold, is the one procedure into an account from the console.
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    expect(screen.queryByText("New invite address")).toBeNull();
    expect(screen.queryByRole("button", { name: "Device code" })).toBeNull();
  });

  it("says if the player has a password", async () => {
    const base = makeStubApi([dayRow({})]);
    await openAde(base);
    expect(screen.getByTestId("account-has-password").textContent).toBe(
      "has a password",
    );
    expect(screen.queryByTestId("account-operator-code")).toBeNull();
  });

  it("shows a live operator's code with its two times", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi = {
      ...base,
      getPlayer: (player) =>
        Promise.resolve(
          playerFixture({
            player,
            has_password: false,
            operator_code: {
              issued_at: "2026-08-12T12:00:00+00:00",
              usable_at: "2026-08-13T12:00:00+00:00",
            },
          }),
        ),
    };
    await openAde(api);
    expect(screen.getByTestId("account-has-password").textContent).toBe(
      "no password set",
    );
    const note = screen.getByTestId("account-operator-code");
    expect(note.textContent).toContain("made 2026-08-12 12:00 UTC");
    expect(note.textContent).toContain("works from 2026-08-13 12:00 UTC");
  });

  it("asks before a revoke, and offers a restore for a revoked player", async () => {
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
    fireEvent.click(screen.getByText("Cancel"));
    expect(api.calls).not.toContain("revoke ade");
    fireEvent.click(screen.getByText("Revoke access"));
    fireEvent.click(screen.getByText("Yes, revoke"));
    expect(await screen.findByText("Restore access")).toBeDefined();
    expect(api.calls).toContain("revoke ade");
    expect(screen.queryByRole("button", { name: "Recovery code" })).toBeNull();
  });

  it("restores a revoked player and prints the recovery code", async () => {
    const base = makeStubApi([dayRow({})]);
    let revoked = true;
    const api: DevApi & { calls: string[] } = {
      ...base,
      getPlayer: async (player) =>
        revoked
          ? playerFixture({ player, status: "revoked" })
          : base.getPlayer(player),
      restorePlayer: async (player) => {
        revoked = false;
        return base.restorePlayer(player);
      },
    };
    await openAde(api);
    fireEvent.click(screen.getByText("Restore access"));
    fireEvent.click(screen.getByText("Yes, restore"));
    const code = await screen.findByTestId("account-recovery-code");
    expect(code.textContent).toBe(RESTORE_CODE);
    expect(api.calls).toContain("restore ade");
    expect(screen.getByText(/ade is active again/)).toBeDefined();
    expect(
      screen.getByText("It works only from 2026-08-13 12:00 UTC."),
    ).toBeDefined();
  });

  it("edits and clears the description with no revoke", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    const field = screen.getByTestId(
      "moderation-description",
    ) as HTMLTextAreaElement;
    expect(field.value).toBe("Sketches in pencil.");
    const save = screen.getByRole("button", { name: "Save" });
    expect((save as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(field, { target: { value: "Kinder words." } });
    fireEvent.click(save);
    expect(await screen.findByText("The description is saved.")).toBeDefined();
    expect(api.calls).toContain("description ade Kinder words.");
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(
      await screen.findByText("The description is cleared."),
    ).toBeDefined();
    expect(api.calls).toContain("description ade ");
    expect(api.calls.some((call) => call.startsWith("revoke"))).toBe(false);
  });

  it("replaces and removes the picture", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi & { calls: string[] } = {
      ...base,
      getPlayer: (player) =>
        Promise.resolve(playerFixture({ player, has_avatar: true })),
    };
    await openAde(api);
    const file = new File([new Uint8Array([137, 80, 78, 71])], "a.png", {
      type: "image/png",
    });
    fireEvent.change(screen.getByTestId("moderation-avatar-file"), {
      target: { files: [file] },
    });
    expect(await screen.findByText("The picture is replaced.")).toBeDefined();
    expect(api.calls).toContain("avatar ade");
    fireEvent.click(screen.getByRole("button", { name: "Remove picture" }));
    expect(await screen.findByText("The picture is removed.")).toBeDefined();
    expect(api.calls).toContain("remove-avatar ade");
  });

  it("deletes an account in two steps: the preview, then the typed name", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    fireEvent.click(screen.getByRole("button", { name: "Delete account" }));
    const preview = await screen.findByTestId("deletion-preview");
    expect(api.calls).toContain("preview ade");
    expect(preview.textContent).toContain("3 days played");
    expect(preview.textContent).toContain("a new anonymous identifier");
    expect(preview.textContent).toContain("This cannot be undone.");
    const go = screen.getByRole("button", {
      name: "Delete permanently",
    }) as HTMLButtonElement;
    expect(go.disabled).toBe(true);
    const confirm = screen.getByTestId("deletion-confirm");
    fireEvent.change(confirm, { target: { value: "Ade" } });
    expect(go.disabled).toBe(true);
    fireEvent.change(confirm, { target: { value: "ade" } });
    expect(go.disabled).toBe(false);
    fireEvent.click(go);
    expect(
      await screen.findByText(
        "ade is deleted. The earlier results show as anon-0123456789abcdef.",
      ),
    ).toBeDefined();
    expect(api.calls).toContain("delete ade ade");
    expect(screen.queryByTestId("deletion-preview")).toBeNull();
  });

  it("cancels a deletion at the preview and deletes nothing", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    fireEvent.click(screen.getByRole("button", { name: "Delete account" }));
    await screen.findByTestId("deletion-preview");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("deletion-preview")).toBeNull();
    expect(api.calls.some((call) => call.startsWith("delete "))).toBe(false);
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
    fireEvent.click(screen.getByText("Build it now"));
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

// ── spec BR1 §7.6: the review of 2026-09-27 ─────────────────────

describe("the console shows what each move did", () => {
  it("shows a refused close in a red box, with the repair for a missing key", async () => {
    const base = makeStubApi([dayRow({ status: "open" })]);
    const api: DevApi = {
      ...base,
      postClose: () =>
        Promise.reject(
          new DevApiError(
            400,
            "OpenRouter API key is missing or empty. Set OPENROUTER_API_KEY in the environment",
          ),
        ),
    };
    render(<DevApp api={api} />);
    fireEvent.click(await screen.findByText("Close the day"));
    fireEvent.click(screen.getByText("Yes, close and score"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("OPENROUTER_API_KEY");
    expect(alert.textContent).toContain("/etc/starvector/env");
  });

  it("shows the close working, then what it did", async () => {
    let release: (value: { trial_rows: number }) => void = () => undefined;
    const gate = new Promise<{ trial_rows: number }>((resolve) => {
      release = resolve;
    });
    const base = makeStubApi([dayRow({ status: "open" })]);
    const api: DevApi = { ...base, postClose: () => gate };
    render(<DevApp api={api} />);
    fireEvent.click(await screen.findByText("Close the day"));
    fireEvent.click(screen.getByText("Yes, close and score"));
    expect(
      await screen.findByText(/Closing 2026-08-12 and scoring each send/),
    ).toBeDefined();
    release({ trial_rows: 3 });
    expect(
      await screen.findByText("Closed 2026-08-12: 3 sends scored."),
    ).toBeDefined();
  });

  it("reveals a closed day behind a newer one, and stays on it", async () => {
    const api = makeStubApi([
      dayRow({ day: "2026-08-19", status: "open" }),
      dayRow({ day: "2026-08-14", status: "closed" }),
    ]);
    render(<DevApp api={api} />);
    await screen.findByText("Close the day");
    fireEvent.change(screen.getByLabelText("stored day"), {
      target: { value: "2026-08-14" },
    });
    fireEvent.click(await screen.findByText("Reveal this day"));
    expect(
      screen.getByText(/2026-08-14 stayed closed behind a newer day/),
    ).toBeDefined();
    fireEvent.click(screen.getByText("Yes, reveal"));
    await waitFor(() => expect(api.lifecycle).toEqual(["reveal 2026-08-14"]));
    expect(await screen.findByText(/Revealed 2026-08-14/)).toBeDefined();
    await waitFor(() =>
      expect(
        (screen.getByLabelText("stored day") as HTMLSelectElement).value,
      ).toBe("2026-08-14"),
    );
    // The latest day's close is not offered while an earlier day shows.
    expect(screen.queryByText("Close the day")).toBeNull();
  });
});

describe("the Players tab after the review", () => {
  it("says when nobody has an account, and offers no account view", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi = {
      ...base,
      getPlayers: () =>
        Promise.resolve({
          players: [
            {
              player: "ade",
              display_name: "ade",
              status: "configured" as const,
              created_at: null,
              devices: 0,
              last_signed_in: null,
              device_codes: 0,
              sends: 3,
            },
          ],
        }),
    };
    render(<DevApp api={api} />);
    openTab("Players");
    expect(
      await screen.findByText(/Nobody has an account on this server yet/),
    ).toBeDefined();
    expect(screen.queryByRole("button", { name: "Manage ade" })).toBeNull();
  });

  it("opens a player's account from the Manage button", async () => {
    const api = makeStubApi([dayRow({})]);
    render(<DevApp api={api} />);
    openTab("Players");
    fireEvent.click(await screen.findByRole("button", { name: "Manage ade" }));
    expect(
      await screen.findByRole("button", { name: "Recovery code" }),
    ).toBeDefined();
  });
});

describe("the Days tab's reloads", () => {
  it("offers no control when the day listing is refused", async () => {
    const base = makeStubApi([]);
    const api: DevApi = {
      ...base,
      getDays: () => Promise.reject(new DevApiError(404, "not found")),
    };
    render(<DevApp api={api} />);
    await screen.findByTestId("console-locked");
    expect(screen.queryByText("Open the next day")).toBeNull();
  });

  it("keeps the newest listing when two reloads cross", async () => {
    let calls = 0;
    let releaseFirst: (value: { days: DevDayRow[] }) => void = () => undefined;
    const base = makeStubApi([dayRow({ status: "closed" })]);
    const api: DevApi = {
      ...base,
      getDays: () => {
        calls += 1;
        if (calls === 1) {
          // The first listing answers last, with the older status.
          return new Promise((resolve) => {
            releaseFirst = resolve;
          });
        }
        return Promise.resolve({ days: [dayRow({ status: "revealed" })] });
      },
    };
    render(<DevApp api={api} />);
    fireEvent.click(screen.getByText("Change token"));
    fireEvent.blur(screen.getByLabelText("operator token"));
    await waitFor(() =>
      expect(screen.getByTestId("day-status").textContent).toBe("Revealed"),
    );
    releaseFirst({ days: [dayRow({ status: "closed" })] });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.getByTestId("day-status").textContent).toBe("Revealed");
  });
});

// ── the console polish: the locked card, the stages, the next step ──

describe("the locked console", () => {
  afterEach(() => {
    window.localStorage.removeItem(TOKEN_KEY);
  });

  const refused = () => Promise.reject(new DevApiError(404, "not found"));

  it("shows one locked card and no tab while the server refuses the token", async () => {
    const base = makeStubApi([dayRow({ status: "open" })]);
    const api: DevApi = { ...base, getDays: refused };
    render(<DevApp api={api} />);
    const card = await screen.findByTestId("console-locked");
    expect(
      within(card).getByRole("heading", { name: "Enter the operator token" }),
    ).toBeDefined();
    const field = within(card).getByLabelText("operator token");
    expect(field.getAttribute("type")).toBe("password");
    expect(within(card).getByText("Operator token")).toBeDefined();
    expect(within(card).getByRole("button", { name: "Unlock" })).toBeDefined();
    // The plain words, with the two causes, and not the raw line.
    expect(card.textContent).toContain(
      "The server answered “not found”. Check the token, or start the server with --dev.",
    );
    expect(screen.queryByText(/^not found:/)).toBeNull();
    // No tab and no skeleton stand beside the card.
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByRole("tabpanel")).toBeNull();
    expect(screen.queryByText("······")).toBeNull();
    expect(screen.queryByText(/behind the latest one/)).toBeNull();
    expect(screen.queryByText(/^loading/i)).toBeNull();
    expect(screen.queryByText("Change token")).toBeNull();
    expect(screen.getByTestId("console-connection").textContent).toBe("Locked");
    // Before a try, the help is a plain line and not an alert.
    expect(within(card).queryByRole("alert")).toBeNull();
  });

  it("unlocks with the button or Enter, and then says Connected", async () => {
    let accepted = false;
    let listings = 0;
    const base = makeStubApi([dayRow({ status: "open" })]);
    const api: DevApi = {
      ...base,
      getDays: () => {
        listings += 1;
        return accepted ? base.getDays() : refused();
      },
    };
    render(<DevApp api={api} />);
    const card = await screen.findByTestId("console-locked");
    const field = within(card).getByLabelText("operator token");
    fireEvent.change(field, { target: { value: "a-wrong-token" } });
    const before = listings;
    fireEvent.click(within(card).getByRole("button", { name: "Unlock" }));
    // A refused try reads the listing again and says so in a red box.
    const alert = await within(card).findByRole("alert");
    expect(alert.textContent).toContain("did not open the console");
    expect(listings).toBeGreaterThan(before);

    accepted = true;
    fireEvent.change(field, { target: { value: "the-operator-token" } });
    const form = field.closest("form");
    if (form === null) {
      throw new Error("the token field has no form");
    }
    // Enter in the field submits the form.
    fireEvent.submit(form);
    expect(await screen.findByRole("tab", { name: "Days" })).toBeDefined();
    expect(screen.queryByTestId("console-locked")).toBeNull();
    expect(screen.getByTestId("console-connection").textContent).toBe(
      "Connected",
    );
    expect(screen.getByText("Change token")).toBeDefined();
    // The storage key is the one from before the polish.
    expect(window.localStorage.getItem(TOKEN_KEY)).toBe("the-operator-token");
    expect(
      await screen.findByRole("button", { name: "Close the day" }),
    ).toBeDefined();
  });

  it("locks again when a changed token is refused", async () => {
    let accepted = true;
    const base = makeStubApi([dayRow({ status: "open" })]);
    const api: DevApi = {
      ...base,
      getDays: () => (accepted ? base.getDays() : refused()),
    };
    render(<DevApp api={api} />);
    fireEvent.click(await screen.findByText("Change token"));
    accepted = false;
    const field = screen.getByLabelText("operator token");
    fireEvent.change(field, { target: { value: "a-wrong-token" } });
    fireEvent.blur(field);
    const card = await screen.findByTestId("console-locked");
    expect(within(card).getByRole("alert").textContent).toContain(
      "did not open the console",
    );
    expect(screen.queryByRole("tab")).toBeNull();
  });

  it("keeps the tabs for a failure that no token repairs", async () => {
    const base = makeStubApi([dayRow({ status: "open" })]);
    const api: DevApi = {
      ...base,
      getDays: () =>
        Promise.reject(new DevApiError(0, "the server did not answer")),
    };
    render(<DevApp api={api} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("the server did not answer");
    expect(screen.queryByTestId("console-locked")).toBeNull();
    expect(screen.getByRole("tab", { name: "Days" })).toBeDefined();
    expect(screen.getByTestId("console-connection").textContent).toBe(
      "Not connected",
    );
  });
});

describe("the day's stage track", () => {
  /** Each stage of the shown day as [stage, state], in sequence. */
  function stages(): Array<[string | null, string | null]> {
    return Array.from(
      document.querySelectorAll(".dev-track [data-stage]"),
      (item) => [
        item.getAttribute("data-stage"),
        item.getAttribute("data-state"),
      ],
    );
  }

  it("shows three stages for a commit-v1 day: no pick after the close", async () => {
    render(
      <DevApp
        api={makeStubApi([dayRow({ status: "open", submitted: false })])}
      />,
    );
    const track = await screen.findByRole("list", { name: "Day stages" });
    expect(stages()).toEqual([
      ["opened", "done"],
      ["close", "current"],
      ["reveal", "pending"],
    ]);
    expect(within(track).queryByText(/Pick photo/)).toBeNull();
    expect(within(track).getByText(/Close and score/)).toBeDefined();
    // The stage that the next move completes is the current step.
    expect(
      track.querySelector('[aria-current="step"]')?.getAttribute("data-stage"),
    ).toBe("close");
    expect(screen.getByText(/picked its photo when it opened/)).toBeDefined();
  });

  it("adds the pick stage for a vp1 day, which has no photo before the close", async () => {
    // The record of a vp1 day holds no target and no commitment until
    // the close (spec VP1 §6).
    render(
      <DevApp
        api={makeStubApi([
          dayRow({
            status: "open",
            submitted: false,
            target_id: null,
            commitment: null,
          }),
        ])}
      />,
    );
    const track = await screen.findByRole("list", { name: "Day stages" });
    expect(stages()).toEqual([
      ["opened", "done"],
      ["close", "current"],
      ["pick", "pending"],
      ["reveal", "pending"],
    ]);
    expect(within(track).getByText(/Pick photo/)).toBeDefined();
    expect(
      screen.getByText(/A public random number picks this day's photo/),
    ).toBeDefined();
    // No photo exists, thus the row does not say that one is hidden,
    // and opening it asks the server for no image.
    expect(screen.getByText("Not picked yet")).toBeDefined();
    expect(screen.queryByText("Hidden so you can stay blind")).toBeNull();
    fireEvent.click(screen.getByText("Show the day's photo"));
    expect(await screen.findByText(/has no photo yet/)).toBeDefined();
    expect(document.querySelector("img.dev-target")).toBeNull();
  });

  it("marks the pick and the close done on a closed vp1 day", async () => {
    render(
      <DevApp
        api={makeStubApi([
          dayRow({ status: "closed", submitted: false, commitment: null }),
        ])}
      />,
    );
    await screen.findByRole("list", { name: "Day stages" });
    expect(stages()).toEqual([
      ["opened", "done"],
      ["close", "done"],
      ["pick", "done"],
      ["reveal", "current"],
    ]);
  });

  it("marks each stage done on a revealed commit-v1 day", async () => {
    render(
      <DevApp
        api={makeStubApi([dayRow({ status: "revealed", submitted: false })])}
      />,
    );
    await screen.findByRole("list", { name: "Day stages" });
    expect(stages()).toEqual([
      ["opened", "done"],
      ["close", "done"],
      ["reveal", "done"],
    ]);
  });

  it("keeps the photo out of the page until the operator asks", async () => {
    const api = makeStubApi([dayRow({ status: "open", submitted: false })]);
    render(<DevApp api={api} />);
    await screen.findByText("Show the day's photo");
    expect(screen.getByText("Hidden so you can stay blind")).toBeDefined();
    // Neither the image nor the target identifier is in the page.
    expect(document.querySelector("img.dev-target")).toBeNull();
    expect(document.body.textContent).not.toContain("t".repeat(64));
    fireEvent.click(screen.getByText("Show the day's photo"));
    expect(await screen.findByAltText("target for 2026-08-12")).toBeDefined();
    fireEvent.click(screen.getByText("Hide the day's photo"));
    expect(document.querySelector("img.dev-target")).toBeNull();
  });
});

describe("the day's numbers and its one next step", () => {
  /** The value of the tile with this label. */
  function tile(label: string): string | null | undefined {
    return screen
      .getByText(label, { selector: ".tile-label" })
      .parentElement?.querySelector(".tile-value")?.textContent;
  }

  it("shows the sends, the close, the photos, and the automatic days", async () => {
    render(<DevApp api={makeStubApi([dayRow({ status: "open" })])} />);
    await screen.findByRole("list", { name: "Day stages" });
    await waitFor(() => expect(tile("Automatic days")).toBe("On"));
    await waitFor(() => expect(tile("Photos in set")).toBe("40"));
    expect(tile("Sends")).toBe("1");
    // The fixture's close instant is in August, before this clock.
    expect(tile("Closes in")).toBe("Due now");
  });

  it("shows a pause from the Automatic days tab on the Days tab", async () => {
    render(<DevApp api={makeStubApi([dayRow({ status: "open" })])} />);
    openTab("Automatic days");
    fireEvent.click(await screen.findByText("Pause automatic days"));
    await screen.findByText("Automatic days are paused");
    openTab("Days");
    expect(tile("Automatic days")).toBe("Paused");
    expect(
      screen.getByText(/Automatic days are paused, so the schedule does not/),
    ).toBeDefined();
  });

  it("offers the close as an outlined danger button, with what it does", async () => {
    render(
      <DevApp
        api={makeStubApi([dayRow({ status: "open", submitted: false })])}
      />,
    );
    const close = await screen.findByRole("button", { name: "Close the day" });
    expect(close.className).toContain("btn-danger");
    expect(close.className).not.toContain("btn-primary");
    expect(screen.getByText("Next step: close the day")).toBeDefined();
    expect(
      screen.getByText(
        /stops new sends and scores everyone\. It can't be reopened\./,
      ),
    ).toBeDefined();
    expect(
      screen.getByText("These controls act on the latest day."),
    ).toBeDefined();
    // The yes of an irreversible move is the solid red button.
    fireEvent.click(close);
    expect(screen.getByText("Yes, close and score").className).toContain(
      "btn-danger-solid",
    );
  });

  it("offers the reveal and the part-way close as danger buttons too", async () => {
    for (const [status, name] of [
      ["closed", "Reveal"],
      ["closing", "Finish closing"],
    ] as const) {
      const view = render(
        <DevApp api={makeStubApi([dayRow({ status, submitted: false })])} />,
      );
      const button = await screen.findByRole("button", { name });
      expect(button.className).toContain("btn-danger");
      expect(button.className).not.toContain("btn-primary");
      view.unmount();
    }
  });

  it("says nothing is due while the schedule waits for the close", async () => {
    const base = makeStubApi([dayRow({ status: "open", submitted: false })]);
    const api: DevApi = {
      ...base,
      getDay: async (day) => ({
        ...(await base.getDay(day)),
        closes_at: "2999-01-01T22:00:00+00:00",
      }),
    };
    render(<DevApp api={api} />);
    expect(await screen.findByText("Nothing is due yet")).toBeDefined();
    expect(
      screen.getByText(
        /The schedule closes this day by itself at 2999-01-01 22:00 UTC/,
      ),
    ).toBeDefined();
    // The close by hand stays, with its confirmation.
    expect(screen.getByRole("button", { name: "Close the day" })).toBeDefined();
  });

  it("keeps the record's raw facts in a row that opens", async () => {
    render(<DevApp api={makeStubApi([dayRow({ status: "open" })])} />);
    const row = (await screen.findByText("Technical details")).closest(
      "details",
    );
    if (row === null) {
      throw new Error("the technical details are not a row that opens");
    }
    expect(row.open).toBe(false);
    expect(within(row).getByText("c".repeat(64))).toBeDefined();
    expect(within(row).getByText("commit-v1")).toBeDefined();
    expect(within(row).getByText("9".repeat(16))).toBeDefined();
    expect(screen.getByText("How a day runs")).toBeDefined();
    // The duplicate of the status badge is gone.
    expect(screen.queryByText(/^status /)).toBeNull();
    expect(screen.getByTestId("day-status").textContent).toBe("Open");
    expect(screen.getByText("Latest day")).toBeDefined();
  });
});

describe("the Automatic days tab after the polish", () => {
  it("lists the next run one time, with the due steps as one sentence", async () => {
    const base = makeStubApi([dayRow({})]);
    const api: DevApi = {
      ...base,
      getSchedule: () =>
        Promise.resolve(
          scheduleFixture({
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
    await screen.findByText("Automatic days are on");
    // One list: the steps of the next run. The due steps are a sentence.
    expect(document.querySelectorAll("#dev-panel-schedule ol")).toHaveLength(1);
    expect(screen.getAllByText("Close 2026-08-12 and score it")).toHaveLength(
      1,
    );
    expect(
      screen.getByText(
        "Close 2026-08-12 and score it, then reveal 2026-08-12, then open 2026-08-13.",
      ),
    ).toBeDefined();
    expect(
      screen.getByText(
        "Does what the timer would do at this moment. The pause does not stop it.",
      ),
    ).toBeDefined();
    const run = screen.getByRole("button", { name: "Do what is due now" });
    expect(run.className).toContain("btn-secondary");
  });

  it("keeps the timer details in a row that opens", async () => {
    render(<DevApp api={makeStubApi([dayRow({})])} />);
    openTab("Automatic days");
    const row = (await screen.findByText("Timer details")).closest("details");
    if (row === null) {
      throw new Error("the timer details are not a row that opens");
    }
    expect(row.open).toBe(false);
    expect(within(row).getByText(/systemctl list-timers/)).toBeDefined();
    expect(row.textContent).toContain("2026-08-12 12:00 UTC");
  });
});

describe("the Players tab after the polish", () => {
  async function openAde(api: DevApi): Promise<void> {
    render(<DevApp api={api} />);
    openTab("Players");
    fireEvent.click(await screen.findByRole("button", { name: "Manage ade" }));
    await screen.findByText("Firefox on Linux");
  }

  /** The section of the account panel with this heading. */
  function group(name: string): HTMLElement {
    const section = screen.getByRole("heading", { name }).closest("section");
    if (section === null) {
      throw new Error(`no group ${name}`);
    }
    return section;
  }

  it("writes the roster headers in sentence case", async () => {
    render(<DevApp api={makeStubApi([dayRow({})])} />);
    openTab("Players");
    await screen.findByRole("button", { name: "Manage ade" });
    const roster = document.querySelector("#roster-panel table");
    expect(
      Array.from(roster?.querySelectorAll("th") ?? [], (th) => th.textContent),
    ).toEqual([
      "Player",
      "Status",
      "Devices",
      "Last sign-in (UTC)",
      "Sends",
      "Created (UTC)",
      "Action",
    ]);
  });

  it("puts each account control in its group", async () => {
    await openAde(makeStubApi([dayRow({})]));
    const help = group("Help them sign in");
    const code = within(help).getByRole("button", { name: "Recovery code" });
    expect(code.className).toContain("btn-secondary");
    expect(code.className).not.toContain("btn-primary");

    const moderate = group("Moderate the profile");
    for (const name of ["Save", "Clear", "Replace picture", "Remove picture"]) {
      expect(within(moderate).getByRole("button", { name })).toBeDefined();
    }
    expect(
      within(moderate).getByTestId("moderation-description"),
    ).toBeDefined();

    const remove = group("Remove access");
    expect(
      within(remove).getByRole("button", { name: "Sign out every device" })
        .className,
    ).toContain("btn-secondary");
    for (const name of ["Revoke access", "Delete account"]) {
      const button = within(remove).getByRole("button", { name });
      expect(button.className).toContain("btn-danger");
      expect(button.className).not.toContain("btn-danger-solid");
    }
    // The devices table stays below the groups.
    expect(screen.getByText("Devices signed in · 1")).toBeDefined();
  });

  it("closes the account panel and moves nothing", async () => {
    const api = makeStubApi([dayRow({})]);
    await openAde(api);
    const before = [...api.calls];
    fireEvent.click(screen.getByRole("button", { name: "Close ade" }));
    expect(
      screen.queryByRole("heading", { name: "Help them sign in" }),
    ).toBeNull();
    expect(screen.queryByText("ade — history")).toBeNull();
    expect(api.calls).toEqual(before);
    // The roster stays, and the panel opens again.
    fireEvent.click(screen.getByRole("button", { name: "Manage ade" }));
    expect(
      await screen.findByRole("heading", { name: "Help them sign in" }),
    ).toBeDefined();
  });
});
