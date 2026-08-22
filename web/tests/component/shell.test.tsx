import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

/** The mock with /api/me replaced by one failure. */
function refusing(error: ApiError) {
  return {
    ...makeMockApi({ today: HARNESS_TODAY }),
    getMe: () => Promise.reject(error),
  };
}

describe("the shell", () => {
  it("renders the nav with the streak tag from /api/me", async () => {
    renderAt("/");
    expect(await screen.findByText("Starvector")).toBeDefined();
    expect(await screen.findByText(/streak/)).toBeDefined();
    expect(screen.getByText("Today")).toBeDefined();
    expect(screen.getByText("Practice")).toBeDefined();
    expect(screen.getByText("History")).toBeDefined();
    expect(screen.getByText("Leaderboard")).toBeDefined();
  });

  it("renders each screen at its path", async () => {
    // Each pattern must name something only that screen renders.
    // "Leaderboard" was matching the nav item, which renders on
    // every path, so the /reveal probe passed without the reveal
    // screen having to render at all.
    const paths: Array<[string, RegExp]> = [
      ["/", /Today's target/],
      ["/practice", /Practice/],
      ["/history", /History/],
      ["/leaderboard", /The day's board/],
      ["/reveal", /Trial score/],
    ];
    for (const [path, expected] of paths) {
      const view = renderAt(path);
      expect(await view.findAllByText(expected)).not.toHaveLength(0);
      view.unmount();
    }
  });

  it("renders the invite gate on a 401", async () => {
    // The production posture: the door probe meets the constant
    // 404, thus the card is the invite copy and nothing else.
    const api = {
      ...refusing(new ApiError(401, undefined, "unauthorized")),
      getDoor: () => Promise.reject(new ApiError(404, undefined, "not found")),
    };
    renderAt("/", api);
    expect(await screen.findByText(/not signed in/)).toBeDefined();
    expect(await screen.findByText(/invite link/)).toBeDefined();
    // The gate replaces the app: no nav, no screen behind it.
    expect(screen.queryByText("Starvector")).toBeNull();
    expect(screen.queryByText("Today")).toBeNull();
    // The client handles no credential (spec M1 §9), thus the gate
    // has nothing to type into when the door is off.
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("grows the door card when the door answers open (spec A1 §4)", async () => {
    // The mock's door is on — the dev world. The invite copy stays
    // and the name field joins it.
    renderAt("/", refusing(new ApiError(401, undefined, "unauthorized")));
    expect(await screen.findByText(/not signed in/)).toBeDefined();
    expect(await screen.findByText(/Dev door/)).toBeDefined();
    expect(await screen.findByLabelText("player name")).toBeDefined();
    expect(
      await screen.findByRole("button", { name: /Create or sign in/ }),
    ).toBeDefined();
  });

  it("does not render the invite gate while the server is down", async () => {
    // The test that matters. A thrown fetch is ApiError(0) and a
    // broken server is a 500; neither means "your invite is not
    // valid here". Telling that reader to go and find a working
    // link sends them somewhere no link helps.
    for (const error of [
      new ApiError(0),
      new ApiError(500, undefined, "boom"),
      new ApiError(404, "not-found"),
    ]) {
      const view = renderAt("/", refusing(error));
      expect(await view.findByText("Starvector")).toBeDefined();
      expect(view.queryByText(/not signed in/)).toBeNull();
      view.unmount();
    }
  });
});
