import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { GITHUB_URL } from "../../src/ui/site-links";
import { HARNESS_TODAY, renderAt } from "./harness";

/** The mock with no session: /api/me answers 401. */
function signedOut(): Api {
  return {
    ...makeMockApi({ today: HARNESS_TODAY }),
    getMe: () => Promise.reject(new ApiError(401, undefined, "unauthorized")),
    getDoor: () => Promise.reject(new ApiError(404, undefined, "not found")),
  };
}

describe("the site footer (spec F1)", () => {
  it("holds the three ways out, and is not a navigation", async () => {
    renderAt("/");
    const footer = await screen.findByRole("contentinfo");
    const links = within(footer).getAllByRole("link");
    expect(links.map((link) => link.textContent?.trim())).toEqual([
      "About",
      "Releases",
      "GitHub (opens in a new tab)",
    ]);
    const github = links[2] as HTMLAnchorElement;
    expect(github.href).toBe(GITHUB_URL);
    expect(github.target).toBe("_blank");
    expect(github.rel).toBe("noreferrer");
    // The app keeps one navigation: the five places, two times.
    expect(within(footer).queryByRole("navigation")).toBeNull();
    // No box for an email address: the owner has not ruled where the
    // addresses go (spec F1 §4).
    expect(within(footer).queryByRole("textbox")).toBeNull();
  });

  it("is on each screen but the two drawing screens", async () => {
    const withFooter = [
      "/",
      "/history",
      "/leaderboard",
      "/reveal",
      "/how",
      "/account",
      "/about",
      "/releases",
    ];
    for (const path of withFooter) {
      const view = renderAt(path);
      expect(await view.findByRole("contentinfo")).toBeDefined();
      view.unmount();
    }
    const drawing: Array<[string, RegExp]> = [
      ["/today", /Review and send/],
      ["/practice", /Check my practice/],
    ];
    for (const [path, expected] of drawing) {
      const view = renderAt(path);
      expect(await view.findAllByText(expected)).not.toHaveLength(0);
      expect(view.queryByRole("contentinfo")).toBeNull();
      view.unmount();
    }
  });

  it("goes to the About page and the Releases page", async () => {
    renderAt("/");
    const footer = await screen.findByRole("contentinfo");
    fireEvent.click(within(footer).getByRole("link", { name: "About" }));
    expect(
      await screen.findByRole("heading", { name: "About Starvector" }),
    ).toBeDefined();
    fireEvent.click(
      within(screen.getByRole("contentinfo")).getByRole("link", {
        name: "Releases",
      }),
    );
    expect(
      await screen.findByRole("heading", { name: "Releases" }),
    ).toBeDefined();
    expect(screen.getByText("No releases to download yet.")).toBeDefined();
    // Signed in, the public pages keep the app around them.
    expect(screen.getAllByRole("navigation", { name: "Main" })).toHaveLength(2);
  });
});

describe("the public pages (spec F1 §3)", () => {
  it("open for a signed-out browser, in place of the gate", async () => {
    for (const [path, heading] of [
      ["/about", "About Starvector"],
      ["/releases", "Releases"],
    ] as const) {
      const view = renderAt(path, signedOut());
      expect(await view.findByRole("heading", { name: heading })).toBeDefined();
      // No gate: no sign-in form, and a way to it when me has
      // answered 401.
      expect(await view.findByRole("link", { name: "Sign in" })).toBeDefined();
      expect(view.queryByRole("heading", { name: "Sign in" })).toBeNull();
      expect(view.queryByLabelText("Password")).toBeNull();
      expect(view.getByRole("contentinfo")).toBeDefined();
      // Not the app: no five places.
      expect(view.queryByRole("navigation")).toBeNull();
      view.unmount();
    }
  });

  it("go to the gate from the brand and from Sign in", async () => {
    renderAt("/about", signedOut());
    fireEvent.click(await screen.findByRole("link", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeDefined();
    // The gate has the footer too.
    expect(screen.getByRole("contentinfo")).toBeDefined();
  });

  it("stay behind the gate for each other path", async () => {
    renderAt("/history", signedOut());
    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeDefined();
    expect(screen.queryByText("Each day you've played")).toBeNull();
  });

  it("open for a player who must agree to the notice", async () => {
    const api = makeMockApi({ today: HARNESS_TODAY, noticeRequired: true });
    const view = renderAt("/about", api);
    expect(
      await view.findByRole("heading", { name: "About Starvector" }),
    ).toBeDefined();
    expect(view.queryByText("Before you play")).toBeNull();
    view.unmount();
    // Each other path keeps the notice screen (spec R1 §3.3).
    renderAt("/history", api);
    expect(await screen.findByText("Before you play")).toBeDefined();
    expect(screen.getByRole("contentinfo")).toBeDefined();
  });
});
