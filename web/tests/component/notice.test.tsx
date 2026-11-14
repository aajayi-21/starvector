import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import type { MockOptions } from "../../src/api/mock";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import {
  NOTICE_BODY,
  NOTICE_LEAD,
  NOTICE_VERSION,
} from "../../src/signin/notice";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

const HEADING = "Before you play";
const REVIEW = "Review and send";
const SEND = "Send today's session";

/** The mock with a count of the consent and the start calls. */
function world(
  options: MockOptions = {},
  overrides: Partial<Api> = {},
): { api: Api; consents: number[]; count: { starts: number } } {
  const mock = makeMockApi({ today: HARNESS_TODAY, ...options });
  const consents: number[] = [];
  const count = { starts: 0 };
  const api: Api = {
    ...mock,
    postConsent: (notice) => {
      consents.push(notice);
      return mock.postConsent(notice);
    },
    startDay: () => {
      count.starts += 1;
      return mock.startDay();
    },
    ...overrides,
  };
  return { api, consents, count };
}

function button(name: string): HTMLButtonElement {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

describe("the blocking notice screen (spec R1 §3.2, §3.3)", () => {
  it("stays away on a server that does not publish results", async () => {
    // The default mock: not agreed, and not required.
    renderAt("/today", world().api);
    await screen.findByText(REVIEW);
    expect(screen.queryByRole("heading", { name: HEADING })).toBeNull();
  });

  it("stays away for a player who agreed to the current notice", async () => {
    const { api } = world({ noticeRequired: true, noticeAgreed: true });
    renderAt("/today", api);
    await screen.findByText(REVIEW);
    expect(screen.queryByRole("heading", { name: HEADING })).toBeNull();
  });

  it("takes the place of each screen until the player agrees", async () => {
    for (const path of ["/", "/today", "/practice", "/account"]) {
      const { api, count } = world({ noticeRequired: true });
      const view = renderAt(path, api);
      const heading = await view.findByRole("heading", { name: HEADING });
      // The notice text, as ruled.
      expect(view.getByText(NOTICE_LEAD).tagName).toBe("STRONG");
      expect(view.getByText(NOTICE_LEAD).parentElement?.textContent).toBe(
        `${NOTICE_LEAD} ${NOTICE_BODY}`,
      );
      expect(button("I agree")).toBeDefined();
      // Focus is on the heading, thus a screen reader says the screen.
      expect(document.activeElement).toBe(heading);
      // No way into the app: no places, no canvas, no send, no start.
      expect(view.queryByRole("navigation")).toBeNull();
      expect(view.queryByTestId("sketch-canvas")).toBeNull();
      expect(view.queryByText(REVIEW)).toBeNull();
      expect(view.queryByText(/saved on this device/)).toBeNull();
      expect(count.starts).toBe(0);
      view.unmount();
    }
  });

  it("posts the version it showed, reads me again, and shows the app", async () => {
    let meReads = 0;
    const base = world({ noticeRequired: true });
    const api: Api = {
      ...base.api,
      getMe: () => {
        meReads += 1;
        return base.api.getMe();
      },
    };
    renderAt("/today", api);
    await screen.findByRole("heading", { name: HEADING });
    const readsBefore = meReads;
    fireEvent.click(button("I agree"));
    // The drawing screen comes back, and the start goes out then.
    await screen.findByText(REVIEW);
    expect(base.consents).toEqual([NOTICE_VERSION]);
    expect(meReads).toBeGreaterThan(readsBefore);
    expect(screen.queryByRole("heading", { name: HEADING })).toBeNull();
    expect(screen.getAllByRole("navigation")).toHaveLength(2);
    await waitFor(() => expect(base.count.starts).toBe(1));
  });

  it("says the page is out of date when the server has a new version", async () => {
    const { api, consents } = world({
      noticeRequired: true,
      noticeVersion: NOTICE_VERSION + 1,
    });
    renderAt("/", api);
    await screen.findByRole("heading", { name: HEADING });
    expect(screen.getByText(/This page is out of date/)).toBeDefined();
    expect(button("Reload")).toBeDefined();
    // The text this page holds is not the current one: no agreement.
    expect(screen.queryByText(NOTICE_LEAD)).toBeNull();
    expect(screen.queryByRole("button", { name: "I agree" })).toBeNull();
    expect(consents).toEqual([]);
    expect(button("Sign out")).toBeDefined();
  });

  it("says the page is out of date on a 409 for the version", async () => {
    // me said the version of this page, and the POST then refuses it.
    const { api } = world(
      { noticeRequired: true },
      {
        postConsent: () => Promise.reject(new ApiError(409, "notice-version")),
      },
    );
    renderAt("/", api);
    await screen.findByRole("heading", { name: HEADING });
    fireEvent.click(button("I agree"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/This page is out of date/);
    expect(alert.textContent).not.toContain("notice-version");
    expect(button("Reload")).toBeDefined();
    expect(screen.queryByRole("button", { name: "I agree" })).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("stays, with the reason, when the agreement does not reach the server", async () => {
    const { api } = world(
      { noticeRequired: true },
      { postConsent: () => Promise.reject(new ApiError(0)) },
    );
    renderAt("/", api);
    await screen.findByRole("heading", { name: HEADING });
    fireEvent.click(button("I agree"));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /Can't reach Starvector/,
    );
    // The player can try again.
    expect(button("I agree").disabled).toBe(false);
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("lets the player sign out with no agreement", async () => {
    const { api, consents } = world({ noticeRequired: true });
    renderAt("/today", api);
    await screen.findByRole("heading", { name: HEADING });
    fireEvent.click(button("Sign out"));
    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeDefined();
    expect(consents).toEqual([]);
  });
});

describe("a send refused for the notice (spec R1 §3.3)", () => {
  async function typeWord(text: string): Promise<void> {
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: text } });
    fireEvent.keyDown(input, { key: "Enter" });
  }

  /**
   * A server that starts to need the agreement while the drawing
   * screen is open: me says agreed until the first send is refused.
   */
  function movedUnder(keepStale: boolean) {
    const base = world({ noticeRequired: true });
    const sends: string[][] = [];
    let stale = true;
    const api: Api = {
      ...base.api,
      getMe: async () => {
        const me = await base.api.getMe();
        return stale ? { ...me, notice: { ...me.notice, agreed: true } } : me;
      },
      submit: (day, record) => {
        sends.push(record.impressions);
        stale = keepStale;
        return base.api.submit(day, record);
      },
    };
    return { ...base, api, sends };
  }

  it("keeps the draft, shows the notice, and sends after the agreement", async () => {
    const { api, sends, consents, count } = movedUnder(false);
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await screen.findByText(REVIEW));
    fireEvent.click(await screen.findByText(SEND));
    // The server refused, me is read again, and the notice shows.
    await screen.findByRole("heading", { name: HEADING });
    expect(
      await screen.findByText(
        "Your unsent sketch and words are still saved on this device.",
      ),
    ).toBeDefined();
    expect(screen.queryByText(/you're in for today/)).toBeNull();
    const saved = window.localStorage.getItem(`sv:draft:${HARNESS_TODAY}`);
    expect(JSON.parse(saved as string).impressions).toEqual(["cold"]);

    fireEvent.click(button("I agree"));
    // The drawing screen comes back with the word on it.
    await screen.findByText(REVIEW);
    expect(await screen.findByLabelText("Remove cold")).toBeDefined();
    expect(consents).toEqual([NOTICE_VERSION]);
    fireEvent.click(screen.getByText(REVIEW));
    fireEvent.click(await screen.findByText(SEND));
    await screen.findByText(/you're in for today/);
    expect(sends).toEqual([["cold"], ["cold"]]);
    // One start for the page load, with two visits of the screen.
    expect(count.starts).toBe(1);
  });

  it("says the work is still on the page while the notice has not shown", async () => {
    // me does not move: the drawing screen stays and says why.
    const { api, sends } = movedUnder(true);
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await screen.findByText(REVIEW));
    fireEvent.click(await screen.findByText(SEND));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(
      "Before you send, you need to agree that your results are public. " +
        "Your sketch and words are still here.",
    );
    expect(sends).toEqual([["cold"]]);
    // Nothing was sent, the word stays, and the review step is closed.
    expect(screen.getByLabelText("Remove cold")).toBeDefined();
    expect(screen.queryByText(/you're in for today/)).toBeNull();
    expect(screen.queryByText(SEND)).toBeNull();
    expect((screen.getByText(REVIEW) as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});
