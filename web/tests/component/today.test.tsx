import { fireEvent, screen, waitFor } from "@testing-library/react";
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

async function typeImpression(text: string): Promise<void> {
  const input = await screen.findByPlaceholderText(
    "one impression — Enter commits",
  );
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
  it("renders the open workspace with code cells and palette", async () => {
    renderAt("/");
    await screen.findByText("Send today's trial");
    const day = await makeMockApi({ today: HARNESS_TODAY }).getDay();
    for (const cell of day.trial_code) {
      expect(screen.getAllByText(cell).length).toBeGreaterThan(0);
    }
    expect(screen.getByLabelText("color ink")).toBeDefined();
    expect(screen.getByLabelText("color teal")).toBeDefined();
    expect(screen.getByText("Send today's trial")).toBeDefined();
  });

  // Spec A1 §9: the extracted intake cards serialize identically
  // to the inline cards they replaced. The literal below is the
  // fixture — an extraction that moves one byte of the wire
  // record fails here.
  it("serializes the extracted cards to the pinned wire record", async () => {
    const sent: unknown[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      submit: (record) => {
        sent.push(record);
        return mock.submit(record);
      },
    };
    const view = renderAt("/", api);
    await screen.findByText("Send today's trial");
    const live = stubCanvasBox(view.container);
    firePointer(live, "pointerdown", 30, 30);
    firePointer(live, "pointermove", 150, 150);
    firePointer(live, "pointerup", 150, 150);
    await typeImpression("tall vertical structure");
    fireEvent.click(screen.getByText("Select strokes"));
    firePointer(live, "pointerdown", 90, 90);
    fireEvent.change(screen.getByPlaceholderText(/what is it/), {
      target: { value: "tower" },
    });
    fireEvent.click(screen.getByText("Group"));
    await screen.findByText("tower");
    fireEvent.click(screen.getByText("Send today's trial"));
    await screen.findByText(/Sent\./);
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
    renderAt("/");
    const send = (await screen.findByText(
      "Send today's trial",
    )) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    await typeImpression("tall vertical structure");
    await waitFor(() => expect(send.disabled).toBe(false));
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
    renderAt("/", api);
    await typeImpression("cold");
    const send = (await screen.findByText(
      "Send today's trial",
    )) as HTMLButtonElement;
    fireEvent.click(send);
    // In flight: the button is disabled — a second click cannot post.
    const sending = (await screen.findByText("Sending…")) as HTMLButtonElement;
    expect(sending.disabled).toBe(true);
    release({ trial_id: "ab".repeat(16), atom_count: 1 });
    expect(await screen.findByText(/Sent\./)).toBeDefined();
    expect(screen.getByText("ab".repeat(16))).toBeDefined();
    expect(screen.getByText(/1 atoms/)).toBeDefined();
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
    renderAt("/", api);
    await typeImpression("cold");
    const send = await screen.findByText("Send today's trial");
    // isPending flips a task late — the ref guard must catch the
    // second click of the same task.
    fireEvent.click(send);
    fireEvent.click(send);
    release({ trial_id: "cd".repeat(16), atom_count: 1 });
    await screen.findByText(/Sent\./);
    expect(calls).toBe(1);
  });

  it("shows friendly copy for an already-submitted 409, not the token", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => Promise.reject(new ApiError(409, "already-submitted")),
    };
    renderAt("/", api);
    await typeImpression("cold");
    fireEvent.click(await screen.findByText("Send today's trial"));
    // The 409 locks the screen into the submitted view.
    expect(await screen.findByText(/Sent\./)).toBeDefined();
    expect(screen.queryByText("already-submitted")).toBeNull();
  });

  it("renders a gate refusal's own detail", async () => {
    const detail =
      "no atom reads into a weighted channel - add an impression, a " +
      "labeled group, or strokes";
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () =>
        Promise.reject(new ApiError(400, "no-scoreable-atom", detail)),
    };
    renderAt("/", api);
    await typeImpression("cold");
    fireEvent.click(await screen.findByText("Send today's trial"));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      detail,
    );
  });

  it("autosaves the draft to localStorage, keyed by day", async () => {
    renderAt("/");
    await typeImpression("water nearby");
    await waitFor(
      () => {
        const raw = window.localStorage.getItem(`sv:draft:${HARNESS_TODAY}`);
        expect(raw).not.toBeNull();
        expect(JSON.parse(raw as string).impressions).toEqual(["water nearby"]);
      },
      { timeout: 2000 },
    );
  });

  it("shows the submitted view when the server says submitted", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({ ...(await base.getDay()), submitted: true }),
    };
    renderAt("/", api);
    expect(await screen.findByText(/Sent\./)).toBeDefined();
    expect(screen.queryByText("Send today's trial")).toBeNull();
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
    renderAt("/", api);
    expect(await screen.findByText(/closes in \d+h \d+m/)).toBeDefined();
  });

  it("stays absent when closes_at is null", async () => {
    renderAt("/");
    await screen.findByText("Send today's trial");
    expect(screen.queryByText(/closes in/)).toBeNull();
  });
});
