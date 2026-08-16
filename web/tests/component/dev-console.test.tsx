import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DevApi } from "../../src/dev/api";
import { DevApiError } from "../../src/dev/api";
import { DevApp, TOKEN_KEY } from "../../src/dev/app";
import { ORIGIN_KEY } from "../../src/dev/invite-panel";
import type { DevDayRow, DevRankings, DevStored } from "../../src/dev/types";

afterEach(() => {
  vi.restoreAllMocks();
});

function dayRow(overrides: Partial<DevDayRow>): DevDayRow {
  return {
    day: "2026-08-12",
    status: "open",
    trial_code: "AAAAAA",
    target_id: "t".repeat(64),
    commitment: "c".repeat(64),
    submitted: true,
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
} {
  const rankingsCalls: string[] = [];
  const lifecycle: string[] = [];
  const mints: Array<[string, string]> = [];
  return {
    rankingsCalls,
    lifecycle,
    mints,
    getDays: () => Promise.resolve({ days }),
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
  };
}

describe("the operator console", () => {
  it("shows the right control for each latest-day status", async () => {
    for (const [status, label] of [
      ["open", "Close the day (scores now)"],
      ["closed", "Reveal"],
      ["revealed", "Open the next day"],
    ] as const) {
      const api = makeStubApi([dayRow({ status, submitted: false })]);
      const view = render(<DevApp api={api} />);
      expect(await screen.findByText(label)).toBeDefined();
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
});
