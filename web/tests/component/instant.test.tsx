import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { MOCK_GUEST, makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { NOTICE_LEAD } from "../../src/signin/notice";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

/** Two strokes: the fake server's floor is two (spec PL1 §8). */
function drawOnCanvas(container: HTMLElement): void {
  const live = container.querySelectorAll("canvas")[1];
  if (live === undefined) {
    throw new Error("no live canvas layer");
  }
  for (const [type, x, y] of [
    ["pointerdown", 30, 30],
    ["pointermove", 150, 150],
    ["pointerup", 150, 150],
    ["pointerdown", 200, 30],
    ["pointermove", 280, 30],
    ["pointerup", 280, 30],
  ] as const) {
    const event = new MouseEvent(type, {
      bubbles: true,
      clientX: x,
      clientY: y,
    });
    Object.defineProperties(event, {
      pointerId: { value: 1 },
      isPrimary: { value: true },
      pointerType: { value: "mouse" },
    });
    fireEvent(live, event);
  }
}

/** A mock world where a sent trial has its result at the first read. */
function quick(options: Parameters<typeof makeMockApi>[0] = {}): Api {
  return makeMockApi({
    today: HARNESS_TODAY,
    instantPendingReads: 0,
    ...options,
  });
}

async function getCode(): Promise<void> {
  fireEvent.click(await screen.findByRole("button", { name: "Get a code" }));
  await screen.findByRole("button", { name: "Send" });
}

describe("the instant trial, for an account", () => {
  it("says what is left today, and that each trial is public", async () => {
    renderAt("/instant", quick());
    expect(
      await screen.findByRole("button", { name: "Get a code" }),
    ).toBeDefined();
    expect(screen.getByText(/of 20 left today/)).toBeDefined();
    expect(screen.getByText(/Every trial is saved and public/)).toBeDefined();
    const modes = screen.getByRole("navigation", { name: "Play modes" });
    expect(
      within(modes)
        .getByRole("link", { name: "Instant trial" })
        .getAttribute("aria-current"),
    ).toBe("page");
  });

  it("gives a code, and gates the send until there is a sketch", async () => {
    const api = quick();
    const { container } = renderAt("/instant", api);
    await getCode();
    const open = (await api.getInstant()).open;
    expect(
      screen.getByRole("img", {
        name: `Code ${[...(open?.trial_code ?? "")].join(" ")}`,
      }),
    ).toBeDefined();
    const send = screen.getByRole("button", { name: "Send" });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    drawOnCanvas(container);
    expect((send as HTMLButtonElement).disabled).toBe(false);
    expect(screen.getByText(/One send for each code/)).toBeDefined();
  });

  it("sends, and shows the photo and the result", async () => {
    const api = quick();
    const { container } = renderAt("/instant", api);
    await getCode();
    drawOnCanvas(container);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const result = await screen.findByRole("region", {
      name: "Instant result",
    });
    expect(result.querySelector(".instant-number")?.textContent).toMatch(
      /^\d+%$/,
    );
    expect(within(result).getByText(/Chance is 50%/)).toBeDefined();
    expect(within(result).getByText("How this photo was picked")).toBeDefined();
    // No hit mark and no cutoff words (rule I2).
    expect(result.textContent).not.toMatch(/\bhit\b|success|correct/i);
    const view = await api.getInstant();
    expect(view.record).toMatchObject({ sent: 1, settled: 1 });
  });

  it("waits for the pulse, then shows the result", async () => {
    const api = makeMockApi({ today: HARNESS_TODAY, instantPendingReads: 1 });
    const { container } = renderAt("/instant", api);
    await getCode();
    drawOnCanvas(container);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const wait = await screen.findByRole("region", {
      name: "Waiting for the photo",
    });
    expect(within(wait).getByText(/drand pulse \d+/)).toBeDefined();
    expect(screen.queryByRole("region", { name: "Instant result" })).toBeNull();
    // The screen reads the trial again, and the result comes.
    expect(
      await screen.findByRole(
        "region",
        { name: "Instant result" },
        { timeout: 4000 },
      ),
    ).toBeDefined();
  });

  it("goes back to a new code with Again", async () => {
    const api = quick();
    const { container } = renderAt("/instant", api);
    await getCode();
    drawOnCanvas(container);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    fireEvent.click(await screen.findByRole("button", { name: "Again" }));
    expect(
      await screen.findByRole("button", { name: "Get a code" }),
    ).toBeDefined();
    expect(screen.getByText(/of 20 left today/).textContent).toMatch(/^19/);
    expect(screen.getByText(/Your record:/).textContent).toMatch(/1 trial/);
  });

  it("opens on the trial that has a code and no send", async () => {
    const api = quick();
    await api.startInstant();
    renderAt("/instant", api);
    expect(await screen.findByRole("button", { name: "Send" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Get a code" })).toBeNull();
  });

  it("shows the refusal of a send, and keeps the sketch", async () => {
    const api: Api = {
      ...quick(),
      sendInstant: () => Promise.reject(new ApiError(503, "clock")),
    };
    const { container } = renderAt("/instant", api);
    await getCode();
    drawOnCanvas(container);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /checks its clock/,
    );
    expect(
      (screen.getByRole("button", { name: "Send" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("says when the day's trials are used", async () => {
    const base = quick();
    const api: Api = {
      ...base,
      getInstant: async () => ({
        ...(await base.getInstant()),
        sent_today: 20,
        left_today: 0,
      }),
    };
    renderAt("/instant", api);
    expect((await screen.findByRole("status")).textContent).toMatch(
      /all 20 instant trials for today/,
    );
    expect(screen.queryByRole("button", { name: "Get a code" })).toBeNull();
  });

  it("says that instant trials are off on a server with the switch off", async () => {
    renderAt("/instant", quick({ instant: "off" }));
    expect(
      await screen.findByText("Instant trials are not open on this server."),
    ).toBeDefined();
    // One mode, thus no switch.
    await waitFor(() =>
      expect(
        screen.queryByRole("navigation", { name: "Play modes" }),
      ).toBeNull(),
    );
  });
});

describe("guest play", () => {
  it("offers an instant trial on the first screen, with no account", async () => {
    const api = quick({ signedIn: false });
    renderAt("/", api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Try an instant trial" }),
    );
    // The notice comes before the guest is made (spec IM1 ruling 6).
    expect(screen.getByText(NOTICE_LEAD)).toBeDefined();
    fireEvent.click(await screen.findByRole("button", { name: "I agree" }));
    expect(
      await screen.findByRole("button", { name: "Get a code" }),
    ).toBeDefined();
    expect(screen.getByText("Playing as a guest")).toBeDefined();
    expect(screen.getByText(/of 5 left today/)).toBeDefined();
    expect((await api.getInstant()).owner).toBe(MOCK_GUEST);
  });

  it("has no guest entry with guest play off", async () => {
    renderAt("/", quick({ signedIn: false, instant: "accounts" }));
    await screen.findByRole("heading", { name: "How it works" });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Try an instant trial" }),
      ).toBeNull(),
    );
  });

  it("shows a guest the instant trial on each path, and a closed door", async () => {
    for (const path of ["/", "/instant", "/history", "/account"]) {
      const view = renderAt(path, quick({ signedIn: false, guest: true }));
      expect(
        await view.findByRole("button", { name: "Get a code" }),
      ).toBeDefined();
      view.unmount();
    }
    renderAt("/today", quick({ signedIn: false, guest: true }));
    expect(
      await screen.findByRole("heading", { name: "Daily challenge" }),
    ).toBeDefined();
    expect(screen.getByText(/needs an account/)).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Make an account" }),
    ).toBeDefined();
  });

  it("sends no daily read for a guest", async () => {
    const calls: string[] = [];
    const base = quick({ signedIn: false, guest: true });
    const api: Api = {
      ...base,
      getDay: () => {
        calls.push("day");
        return base.getDay();
      },
      getHistory: () => {
        calls.push("history");
        return base.getHistory();
      },
      getRevealedDays: () => {
        calls.push("days");
        return base.getRevealedDays();
      },
    };
    renderAt("/today", api);
    await screen.findByRole("heading", { name: "Daily challenge" });
    expect(calls).toEqual([]);
  });

  it("invites a guest to make an account after a result", async () => {
    const api = quick({ signedIn: false, guest: true });
    const { container } = renderAt("/instant", api);
    await getCode();
    drawOnCanvas(container);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const result = await screen.findByRole("region", {
      name: "Instant result",
    });
    fireEvent.click(
      within(result).getByRole("button", { name: "Make an account" }),
    );
    // The gate screen, with the way back to guest play.
    expect(
      await screen.findByRole("button", {
        name: "Back to your instant trials",
      }),
    ).toBeDefined();
    fireEvent.click(
      screen.getByRole("button", { name: "Back to your instant trials" }),
    );
    expect(await screen.findByText("Playing as a guest")).toBeDefined();
  });

  it("asks a guest to agree to a new notice version", async () => {
    const base = quick({ signedIn: false, guest: true });
    let agreed = false;
    const api: Api = {
      ...base,
      getInstant: async () => ({
        ...(await base.getInstant()),
        needs_agreement: !agreed,
      }),
      makeGuest: (agrees: boolean) => {
        agreed = agrees;
        return base.makeGuest(agrees);
      },
    };
    renderAt("/instant", api);
    expect(
      await screen.findByRole("heading", { name: "Before you play" }),
    ).toBeDefined();
    expect(screen.getByText(NOTICE_LEAD)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "I agree" }));
    expect(
      await screen.findByRole("button", { name: "Get a code" }),
    ).toBeDefined();
  });
});
