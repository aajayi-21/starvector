import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { formatInstant } from "../../src/ui/format";
import { HARNESS_TODAY, renderAt } from "./harness";

/** Made a day ago and usable far ahead: the hold is still on. */
const HELD = {
  issued_at: "2026-08-13T10:00:00+00:00",
  usable_at: "2999-01-01T10:00:00+00:00",
};
/** Past its hold: the code works now. */
const WORKING = {
  issued_at: "2026-08-13T10:00:00+00:00",
  usable_at: "2026-08-14T10:00:00+00:00",
};

function withCode(code: typeof HELD): Api {
  return makeMockApi({ today: HARNESS_TODAY, operatorCode: code });
}

describe("the notice of an operator's recovery code (spec A2 §6.1)", () => {
  it("shows nothing with no operator's code", async () => {
    renderAt("/");
    await screen.findByText(/Today's photo is hidden/);
    expect(screen.queryByRole("button", { name: "Stop this" })).toBeNull();
    expect(screen.queryByText(/by the operator/)).toBeNull();
  });

  it("shows on each screen of the signed-in app, with the two times", async () => {
    for (const path of ["/", "/account", "/leaderboard", "/today"]) {
      const view = renderAt(path, withCode(HELD));
      const notice = await view.findByRole("alert");
      expect(notice.textContent).toContain(
        `A recovery code was made for your account by the operator on ${formatInstant(HELD.issued_at)}.`,
      );
      expect(notice.textContent).toContain(
        `It starts working at ${formatInstant(HELD.usable_at)}.`,
      );
      expect(notice.textContent).toContain(
        "If you did not ask for this, stop it.",
      );
      expect(view.getByRole("button", { name: "Stop this" })).toBeDefined();
      view.unmount();
    }
  });

  it("says a code past its hold works now", async () => {
    renderAt("/", withCode(WORKING));
    const notice = await screen.findByRole("alert");
    expect(notice.textContent).toContain(
      `It has worked since ${formatInstant(WORKING.usable_at)}.`,
    );
    expect(screen.getByRole("button", { name: "Stop this" })).toBeDefined();
  });

  it("stops the code with no password and reads me again", async () => {
    const calls: string[] = [];
    const mock = withCode(HELD);
    const api: Api = {
      ...mock,
      getMe: () => {
        calls.push("me");
        return mock.getMe();
      },
      stopOperatorCode: () => {
        calls.push("stop");
        return mock.stopOperatorCode();
      },
    };
    renderAt("/account", api);
    fireEvent.click(await screen.findByRole("button", { name: "Stop this" }));
    // The notice goes with the code.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Stop this" })).toBeNull(),
    );
    expect(screen.queryByText(/by the operator/)).toBeNull();
    // One stop, with no field to type in, and a read of me after it.
    expect(calls.filter((call) => call === "stop")).toHaveLength(1);
    expect(calls.lastIndexOf("me")).toBeGreaterThan(calls.indexOf("stop"));
  });

  it("keeps the notice and says so when the stop fails", async () => {
    const api: Api = {
      ...withCode(HELD),
      stopOperatorCode: () => Promise.reject(new ApiError(0)),
    };
    renderAt("/", api);
    fireEvent.click(await screen.findByRole("button", { name: "Stop this" }));
    expect(await screen.findByText(/Can't reach Starvector/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Stop this" })).toBeDefined();
  });

  it("is not on the gate screen: a signed-out device shows no notice", async () => {
    renderAt(
      "/",
      makeMockApi({
        today: HARNESS_TODAY,
        operatorCode: HELD,
        signedIn: false,
      }),
    );
    await screen.findByRole("heading", { name: "Sign in" });
    expect(screen.queryByRole("button", { name: "Stop this" })).toBeNull();
  });
});
