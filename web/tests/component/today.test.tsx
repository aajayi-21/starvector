import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const SEND = "Send today's session";

async function typeWord(text: string): Promise<void> {
  const input = await screen.findByLabelText("Add a word");
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

/** The practice tests' drawing helper, with a real 300x300 box. */
function stubCanvasBox(container: HTMLElement): HTMLCanvasElement {
  const live = container.querySelectorAll("canvas")[1];
  if (live === undefined) {
    throw new Error("no live canvas layer");
  }
  vi.spyOn(live, "getBoundingClientRect").mockReturnValue({
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: 300,
    bottom: 300,
    width: 300,
    height: 300,
    toJSON: () => ({}),
  } as DOMRect);
  return live;
}

function firePointer(
  target: HTMLElement,
  type: string,
  x: number,
  y: number,
): void {
  const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y });
  Object.defineProperties(event, {
    pointerId: { value: 1 },
    isPrimary: { value: true },
    pointerType: { value: "mouse" },
  });
  fireEvent(target, event);
}

describe("the Today screen", () => {
  it("renders the code, the canvas, the colors, and one send button", async () => {
    renderAt("/today");
    await screen.findByText(SEND);
    const day = await makeMockApi({ today: HARNESS_TODAY }).getDay();
    expect(
      screen.getByRole("img", {
        name: `Code ${[...day.trial_code].join(" ")}`,
      }),
    ).toBeDefined();
    expect(screen.getByLabelText("white ink")).toBeDefined();
    expect(screen.getByLabelText("teal ink")).toBeDefined();
    expect(screen.getByTestId("sketch-canvas")).toBeDefined();
    expect(screen.getAllByText(SEND)).toHaveLength(1);
    // No jargon on the player's screen.
    expect(screen.queryByText(/commitment/i)).toBeNull();
    expect(screen.queryByText(/impression/i)).toBeNull();
    expect(screen.queryByText(/trial/i)).toBeNull();
  });

  // Spec A1 §9: the extracted intake cards serialize identically
  // to the inline cards they replaced. The literal below is the
  // fixture — a change that moves one byte of the wire record
  // fails here.
  it("serializes the cards to the pinned wire record", async () => {
    const sent: unknown[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      submit: (record) => {
        sent.push(record);
        return mock.submit(record);
      },
    };
    const view = renderAt("/today", api);
    await screen.findByText(SEND);
    const live = stubCanvasBox(view.container);
    firePointer(live, "pointerdown", 30, 30);
    firePointer(live, "pointermove", 150, 150);
    firePointer(live, "pointerup", 150, 150);
    await typeWord("tall vertical structure");
    fireEvent.click(screen.getByText("Pick strokes"));
    firePointer(live, "pointerdown", 90, 90);
    fireEvent.change(screen.getByLabelText("Name the picked strokes"), {
      target: { value: "tower" },
    });
    fireEvent.click(screen.getByText("Label"));
    await screen.findByText("tower");
    fireEvent.click(screen.getByText(SEND));
    await screen.findByText(/you're in for today/);
    expect(sent).toEqual([
      {
        impressions: ["tall vertical structure"],
        canvas_strokes: [
          {
            points: [
              [0.1, 0.1],
              [0.5, 0.5],
            ],
            group_id: "g1",
          },
        ],
        groups: [{ id: "g1", label: "tower" }],
        relations: [],
        pasted_text: null,
      },
    ]);
  });

  it("disables send until something is scoreable", async () => {
    renderAt("/today");
    const send = (await screen.findByText(SEND)) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(
      screen.getByText(/Draw something or add a word first/),
    ).toBeDefined();
    await typeWord("tall vertical structure");
    await waitFor(() => expect(send.disabled).toBe(false));
    expect(screen.getByText(/You can send once/)).toBeDefined();
  });

  it("adds a word with the Add button, not only with Enter", async () => {
    renderAt("/today");
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "cold" } });
    fireEvent.click(screen.getByText("Add"));
    expect(await screen.findByLabelText("Remove cold")).toBeDefined();
    fireEvent.click(screen.getByLabelText("Remove cold"));
    await waitFor(() =>
      expect(screen.queryByLabelText("Remove cold")).toBeNull(),
    );
  });

  it("locks the button while the send is in flight", async () => {
    let release: (value: { trial_id: string; atom_count: number }) => void =
      () => undefined;
    const gate = new Promise<{ trial_id: string; atom_count: number }>(
      (resolve) => {
        release = resolve;
      },
    );
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => gate,
    };
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await screen.findByText(SEND));
    // In flight: the button is disabled — a second click cannot post.
    const sending = (await screen.findByText("Sending…")) as HTMLButtonElement;
    expect(sending.disabled).toBe(true);
    release({ trial_id: "ab".repeat(16), atom_count: 1 });
    expect(await screen.findByText(/you're in for today/)).toBeDefined();
  });

  it("fires exactly one POST for a synchronous double-click", async () => {
    let calls = 0;
    let release: (value: { trial_id: string; atom_count: number }) => void =
      () => undefined;
    const gate = new Promise<{ trial_id: string; atom_count: number }>(
      (resolve) => {
        release = resolve;
      },
    );
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => {
        calls += 1;
        return gate;
      },
    };
    renderAt("/today", api);
    await typeWord("cold");
    const send = await screen.findByText(SEND);
    // isPending flips a task late — the ref guard must catch the
    // second click of the same task.
    fireEvent.click(send);
    fireEvent.click(send);
    release({ trial_id: "cd".repeat(16), atom_count: 1 });
    await screen.findByText(/you're in for today/);
    expect(calls).toBe(1);
  });

  it("shows the sent view for an already-submitted 409, not the token", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => Promise.reject(new ApiError(409, "already-submitted")),
    };
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await screen.findByText(SEND));
    // The 409 locks the screen into the sent view.
    expect(await screen.findByText(/you're in for today/)).toBeDefined();
    expect(screen.queryByText("already-submitted")).toBeNull();
  });

  it("renders a refusal in plain words", async () => {
    const detail =
      "no atom reads into a weighted channel - add an impression, a " +
      "labeled group, or strokes";
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () =>
        Promise.reject(new ApiError(400, "no-scoreable-atom", detail)),
    };
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await screen.findByText(SEND));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(
      "Add at least one word or a few strokes before you send.",
    );
  });

  it("autosaves the draft to localStorage, keyed by day", async () => {
    renderAt("/today");
    await typeWord("water nearby");
    await waitFor(
      () => {
        const raw = window.localStorage.getItem(`sv:draft:${HARNESS_TODAY}`);
        expect(raw).not.toBeNull();
        expect(JSON.parse(raw as string).impressions).toEqual(["water nearby"]);
      },
      { timeout: 2000 },
    );
  });

  it("shows the sent view when the server says sent", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({ ...(await base.getDay()), submitted: true }),
    };
    renderAt("/today", api);
    expect(await screen.findByText(/you're in for today/)).toBeDefined();
    expect(screen.queryByText(SEND)).toBeNull();
  });

  it("treats a closing day as closed", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({ ...(await base.getDay()), status: "closing" }),
    };
    renderAt("/today", api);
    expect(await screen.findByText("Today's session has closed")).toBeDefined();
    expect(screen.queryByText(SEND)).toBeNull();
  });

  it("points at practice when no day is open", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getDay: () => Promise.reject(new ApiError(404, undefined, "no day open")),
    };
    renderAt("/today", api);
    expect(
      await screen.findByText("No session is open right now"),
    ).toBeDefined();
    expect(
      within(screen.getByRole("main")).getByRole("link", { name: "Practice" }),
    ).toBeDefined();
  });
});

describe("the countdown", () => {
  it("renders when the day carries closes_at", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({
        ...(await base.getDay()),
        closes_at: "2099-01-01T22:00:00+00:00",
      }),
    };
    renderAt("/today", api);
    expect(await screen.findByText(/Closes in \d+ h/)).toBeDefined();
  });

  it("stays absent when closes_at is null or past", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({
        ...(await base.getDay()),
        closes_at: "2001-01-01T22:00:00+00:00",
      }),
    };
    renderAt("/today", api);
    await screen.findByText(SEND);
    expect(screen.queryByText(/Closes in/)).toBeNull();
  });
});
