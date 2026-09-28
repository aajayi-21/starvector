import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

/** The mock with /api/me replaced by one failure. */
function refusing(error: ApiError): Api {
  return {
    ...makeMockApi({ today: HARNESS_TODAY }),
    getMe: () => Promise.reject(error),
  };
}

describe("the shell", () => {
  it("renders the five places, the streak, and the account link", async () => {
    renderAt("/");
    const nav = await screen.findAllByRole("navigation", { name: "Main" });
    // The top bar and the phone tab bar hold the same five places.
    expect(nav).toHaveLength(2);
    const top = nav[0] as HTMLElement;
    for (const name of [
      "Home",
      "Today",
      "Practice",
      "Your results",
      "Leaderboard",
    ]) {
      expect(within(top).getByRole("link", { name })).toBeDefined();
    }
    expect(await screen.findByText(/-day streak/)).toBeDefined();
    expect(screen.getByLabelText("Your account")).toBeDefined();
  });

  it("renders each screen at its path", async () => {
    // Each pattern names something only that screen renders.
    const paths: Array<[string, RegExp]> = [
      ["/", /Today's photo is hidden behind this code/],
      ["/today", /Send today's session/],
      ["/practice", /Replay a past day's photo/],
      ["/history", /Each day you've played/],
      ["/leaderboard", /The latest day's results/],
      ["/reveal", /You beat \d+% of the photos/],
      ["/how", /How Starvector works/],
      ["/account", /Your data/],
    ];
    for (const [path, expected] of paths) {
      const view = renderAt(path);
      expect(await view.findAllByText(expected)).not.toHaveLength(0);
      view.unmount();
    }
  });

  it("says a test season is a test season", async () => {
    renderAt("/");
    expect(await screen.findByText(/Test season/)).toBeDefined();
  });

  it("says nothing about a season when the pool is public", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getAbout: () =>
        Promise.resolve({
          test_season: false,
          photo_count: 7500,
          closes_at_utc: "22:00",
        }),
    };
    renderAt("/", api);
    await screen.findByText(/Today's photo is hidden/);
    expect(screen.queryByText(/Test season/)).toBeNull();
  });
});

describe("the signed-out landing page", () => {
  it("renders on a 401 in place of the app", async () => {
    const api = {
      ...refusing(new ApiError(401, undefined, "unauthorized")),
      getDoor: () => Promise.reject(new ApiError(404, undefined, "not found")),
    };
    renderAt("/history", api);
    expect(
      await screen.findByText("A new hidden photo every day."),
    ).toBeDefined();
    expect(screen.getByText("How it works")).toBeDefined();
    expect(screen.getByText(/open the invite link/)).toBeDefined();
    // The landing replaces the app: no navigation, no screen behind.
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByText("Your results")).toBeNull();
    // With the door off, the device code is the one thing to type.
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByLabelText("Signed in on another device?")).toBeDefined();
    expect(screen.queryByText("Test server sign-in")).toBeNull();
  });

  it("signs in with a device code and then shows the app", async () => {
    let signedIn = false;
    const codes: string[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      getMe: () =>
        signedIn
          ? mock.getMe()
          : Promise.reject(new ApiError(401, undefined, "unauthorized")),
      getDoor: () => Promise.reject(new ApiError(404, undefined, "not found")),
      redeemDeviceCode: (code) => {
        codes.push(code);
        signedIn = true;
        return Promise.resolve({ player: "ade", display_name: "ade" });
      },
    };
    renderAt("/", api);
    const field = await screen.findByLabelText("Signed in on another device?");
    const submit = screen.getByRole("button", { name: "Sign in" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(field, { target: { value: "abcd-efgh" } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => expect(codes).toEqual(["abcd-efgh"]));
    expect(await screen.findByText(/Today's photo is hidden/)).toBeDefined();
  });

  it("says why a bad code did not work", async () => {
    const api: Api = {
      ...refusing(new ApiError(401, undefined, "unauthorized")),
      getDoor: () => Promise.reject(new ApiError(404, undefined, "not found")),
      redeemDeviceCode: () => Promise.reject(new ApiError(400, "bad-code")),
    };
    renderAt("/", api);
    const field = await screen.findByLabelText("Signed in on another device?");
    fireEvent.change(field, { target: { value: "ZZZZ-ZZZZ" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /works once and expires after 10 minutes/,
    );
  });

  it("adds the name sign-in on a test server (spec A1 §4)", async () => {
    // The mock's door is on — the dev world.
    renderAt("/", refusing(new ApiError(401, undefined, "unauthorized")));
    expect(await screen.findByText("Test server sign-in")).toBeDefined();
    expect(await screen.findByLabelText("Player name")).toBeDefined();
    expect(
      await screen.findByRole("button", { name: "Sign in by name" }),
    ).toBeDefined();
  });

  it("does not render while the server is down", async () => {
    // A thrown fetch is ApiError(0) and a broken server is a 500;
    // neither means "sign in here". Sending that reader to look
    // for an invite sends them somewhere no invite helps.
    for (const error of [
      new ApiError(0),
      new ApiError(500, undefined, "boom"),
      new ApiError(404, "not-found"),
    ]) {
      const view = renderAt("/", refusing(error));
      expect(await view.findAllByRole("navigation")).not.toHaveLength(0);
      expect(view.queryByText("A new hidden photo every day.")).toBeNull();
      view.unmount();
    }
  });
});
