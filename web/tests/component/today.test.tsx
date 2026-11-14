import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import type { SubmissionAck, WireRecord } from "../../src/api/types";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const REVIEW = "Review and send";
const SEND = "Send today's session";

/** Open the review step, and give the button that sends. */
async function openReview(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByText(REVIEW));
  return screen.findByText(SEND);
}

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
    await screen.findByText(REVIEW);
    const day = await makeMockApi({ today: HARNESS_TODAY }).getDay();
    expect(
      screen.getByRole("img", {
        name: `Code ${[...day.trial_code].join(" ")}`,
      }),
    ).toBeDefined();
    expect(screen.getByLabelText("white ink")).toBeDefined();
    expect(screen.getByLabelText("teal ink")).toBeDefined();
    expect(screen.getByTestId("sketch-canvas")).toBeDefined();
    expect(screen.getAllByText(REVIEW)).toHaveLength(1);
    expect(screen.queryByText(SEND)).toBeNull();
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
      submit: (day, record) => {
        sent.push(record);
        return mock.submit(day, record);
      },
    };
    const view = renderAt("/today", api);
    await screen.findByText(REVIEW);
    const live = stubCanvasBox(view.container);
    firePointer(live, "pointerdown", 30, 30);
    firePointer(live, "pointermove", 150, 150);
    firePointer(live, "pointerup", 150, 150);
    firePointer(live, "pointerdown", 200, 30);
    firePointer(live, "pointermove", 280, 30);
    firePointer(live, "pointerup", 280, 30);
    await typeWord("tall vertical structure");
    fireEvent.click(screen.getByText("Pick strokes"));
    firePointer(live, "pointerdown", 90, 90);
    fireEvent.change(screen.getByLabelText("Name the picked strokes"), {
      target: { value: "tower" },
    });
    fireEvent.click(screen.getByText("Label"));
    await screen.findByText("tower");
    fireEvent.click(await openReview());
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
          {
            points: [
              [0.6667, 0.1],
              [0.9333, 0.1],
            ],
            group_id: null,
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
    const send = (await screen.findByText(REVIEW)) as HTMLButtonElement;
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
    let release: (value: SubmissionAck) => void = () => undefined;
    const gate = new Promise<SubmissionAck>((resolve) => {
      release = resolve;
    });
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => gate,
    };
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await openReview());
    // In flight: the button is disabled — a second click cannot post.
    const sending = (await screen.findByText("Sending…")) as HTMLButtonElement;
    expect(sending.disabled).toBe(true);
    release({ trial_id: "ab".repeat(16), day: HARNESS_TODAY, atom_count: 1 });
    expect(await screen.findByText(/you're in for today/)).toBeDefined();
  });

  it("fires exactly one POST for a synchronous double-click", async () => {
    let calls = 0;
    let release: (value: SubmissionAck) => void = () => undefined;
    const gate = new Promise<SubmissionAck>((resolve) => {
      release = resolve;
    });
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => {
        calls += 1;
        return gate;
      },
    };
    renderAt("/today", api);
    await typeWord("cold");
    const send = await openReview();
    // isPending flips a task late — the ref guard must catch the
    // second click of the same task.
    fireEvent.click(send);
    fireEvent.click(send);
    release({ trial_id: "cd".repeat(16), day: HARNESS_TODAY, atom_count: 1 });
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
    fireEvent.click(await openReview());
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
    fireEvent.click(await openReview());
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
    await screen.findByText(REVIEW);
    expect(screen.queryByText(/Closes in/)).toBeNull();
  });
});

function drawTwoStrokes(container: HTMLElement): void {
  const live = stubCanvasBox(container);
  drawOneStroke(live, 30);
  drawOneStroke(live, 120);
}

function drawOneStroke(live: HTMLCanvasElement, y: number): void {
  firePointer(live, "pointerdown", 30, y);
  firePointer(live, "pointermove", 150, y);
  firePointer(live, "pointerup", 150, y);
}

describe("the review step", () => {
  it("sends nothing until the second button", async () => {
    let calls = 0;
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      submit: (day, record) => {
        calls += 1;
        return mock.submit(day, record);
      },
    };
    renderAt("/today", api);
    await typeWord("cold");
    await openReview();
    expect(calls).toBe(0);
    expect(screen.getByText("Check before you send")).toBeDefined();
    expect(screen.getByText("cold", { selector: "p" })).toBeDefined();
    fireEvent.click(screen.getByText("Keep editing"));
    expect(screen.queryByText("Check before you send")).toBeNull();
    expect(calls).toBe(0);
  });

  it("offers a typed word and includes it", async () => {
    const sent: WireRecord[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      submit: (day, record) => {
        sent.push(record);
        return mock.submit(day, record);
      },
    };
    renderAt("/today", api);
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "  cold  " } });
    const send = await openReview();
    expect(screen.getByLabelText(/Include “cold”/)).toBeDefined();
    fireEvent.click(send);
    await screen.findByText(/you're in for today/);
    expect(sent[0]?.impressions).toEqual(["cold"]);
  });

  it("leaves a typed word out when the box is off", async () => {
    const sent: WireRecord[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      submit: (day, record) => {
        sent.push(record);
        return mock.submit(day, record);
      },
    };
    renderAt("/today", api);
    await typeWord("kept");
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "dropped" } });
    const send = await openReview();
    fireEvent.click(screen.getByLabelText(/Include “dropped”/));
    fireEvent.click(send);
    await screen.findByText(/you're in for today/);
    expect(sent[0]?.impressions).toEqual(["kept"]);
  });

  it("waits when the only word is typed and its box is off", async () => {
    renderAt("/today");
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "only" } });
    const send = (await openReview()) as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    fireEvent.click(screen.getByLabelText(/Include “only”/));
    expect(send.disabled).toBe(true);
  });

  it("keeps Send off at one stroke, with the reason", async () => {
    const view = renderAt("/today");
    const review = (await screen.findByText(REVIEW)) as HTMLButtonElement;
    const live = stubCanvasBox(view.container);
    drawOneStroke(live, 30);
    await screen.findByText(/at least 2 strokes/);
    expect(review.disabled).toBe(true);
    drawOneStroke(live, 120);
    await waitFor(() => expect(review.disabled).toBe(false));
  });

  it("keeps Send off at one stroke with words too", async () => {
    // Layer 0 refuses a drawing below the floor whatever comes with it.
    const view = renderAt("/today");
    const review = (await screen.findByText(REVIEW)) as HTMLButtonElement;
    drawOneStroke(stubCanvasBox(view.container), 30);
    await typeWord("cold");
    expect(review.disabled).toBe(true);
  });
});

describe("the stale tab and the rollover", () => {
  it("names the day it was composed for", async () => {
    const days: string[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      submit: (day, record) => {
        days.push(day);
        return mock.submit(day, record);
      },
    };
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await openReview());
    await screen.findByText(/you're in for today/);
    expect(days).toEqual([HARNESS_TODAY]);
  });

  it("keeps the draft on a day-moved 409 and asks", async () => {
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const later = "2026-08-15";
    let current = HARNESS_TODAY;
    const api: Api = {
      ...mock,
      getDay: async () => ({ ...(await mock.getDay()), day: current }),
      submit: () => {
        current = later;
        return Promise.reject(new ApiError(409, "day-moved"));
      },
    };
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await openReview());
    // The sketch stays, and nothing sends until the player chooses.
    const keep = await screen.findByText("Keep it for today");
    expect(screen.getByText("cold")).toBeDefined();
    expect(screen.queryByText(/you're in for today/)).toBeNull();
    const review = screen.getByText(REVIEW) as HTMLButtonElement;
    expect(review.disabled).toBe(true);
    fireEvent.click(keep);
    await waitFor(() => expect(review.disabled).toBe(false));
    expect(screen.queryByText("Keep it for today")).toBeNull();
    expect(screen.getByText("cold")).toBeDefined();
  });

  it("clears the sketch when the player starts clean", async () => {
    const mock = makeMockApi({ today: HARNESS_TODAY });
    let current = HARNESS_TODAY;
    const api: Api = {
      ...mock,
      getDay: async () => ({ ...(await mock.getDay()), day: current }),
      submit: () => {
        current = "2026-08-15";
        return Promise.reject(new ApiError(409, "day-moved"));
      },
    };
    renderAt("/today", api);
    await typeWord("cold");
    fireEvent.click(await openReview());
    fireEvent.click(await screen.findByText("Start clean"));
    await waitFor(() => expect(screen.queryByText("cold")).toBeNull());
    expect(window.localStorage.getItem(`sv:draft:${HARNESS_TODAY}`)).toBeNull();
  });

  it("brings back an unsent sketch from an earlier day", async () => {
    window.localStorage.setItem(
      "sv:draft:2026-08-10",
      JSON.stringify({
        doc: { strokes: [], groups: [], relations: [] },
        impressions: ["left over"],
        pastedText: "",
        nextStrokeId: 1,
      }),
    );
    renderAt("/today");
    expect(await screen.findByText("Keep it for today")).toBeDefined();
    expect(screen.getByText("left over")).toBeDefined();
    expect(screen.getByRole("alert").textContent).toMatch(/has closed/);
  });

  it("asks nothing for an empty earlier draft", async () => {
    window.localStorage.setItem(
      "sv:draft:2026-08-10",
      JSON.stringify({
        doc: { strokes: [], groups: [], relations: [] },
        impressions: [],
        pastedText: "",
        nextStrokeId: 1,
      }),
    );
    renderAt("/today");
    await screen.findByText(REVIEW);
    expect(screen.queryByText("Keep it for today")).toBeNull();
  });

  it("forgets earlier drafts after a send", async () => {
    window.localStorage.setItem(
      "sv:draft:2026-08-10",
      JSON.stringify({
        doc: { strokes: [], groups: [], relations: [] },
        impressions: ["left over"],
        pastedText: "",
        nextStrokeId: 1,
      }),
    );
    renderAt("/today");
    fireEvent.click(await screen.findByText("Keep it for today"));
    fireEvent.click(await openReview());
    await screen.findByText(/you're in for today/);
    expect(window.localStorage.getItem("sv:draft:2026-08-10")).toBeNull();
  });

  it("names the session in the sent view", async () => {
    renderAt("/today");
    await typeWord("cold");
    fireEvent.click(await openReview());
    expect(
      await screen.findByText(/locked in for the session of/),
    ).toBeDefined();
  });

  it("says a closed day's sketch is saved", async () => {
    const mock = makeMockApi({ today: HARNESS_TODAY });
    window.localStorage.setItem(
      `sv:draft:${HARNESS_TODAY}`,
      JSON.stringify({
        doc: { strokes: [], groups: [], relations: [] },
        impressions: ["unsent"],
        pastedText: "",
        nextStrokeId: 1,
      }),
    );
    const api: Api = {
      ...mock,
      getDay: async () => ({ ...(await mock.getDay()), status: "closing" }),
    };
    renderAt("/today", api);
    expect(
      await screen.findByText(/unsent sketch wasn't scored/),
    ).toBeDefined();
    expect(screen.getByText(/updates by itself/)).toBeDefined();
  });

  it("states the close in local time", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({
        ...(await base.getDay()),
        closes_at: "2099-01-01T22:00:00+00:00",
      }),
    };
    renderAt("/today", api);
    expect(await screen.findByText(/Today's session · closes/)).toBeDefined();
    const badge = await screen.findByText(/Closes in \d+ h/);
    expect(badge.textContent).toMatch(/\(.*\d:\d\d.*\)/);
  });

  it("names no side of the screen in the hints", async () => {
    const view = renderAt("/today");
    await screen.findByText(REVIEW);
    drawTwoStrokes(view.container);
    await screen.findByText(/Keep going, or add some words/);
    expect(view.container.textContent).not.toMatch(/on the right/);
  });
});

/** The link of a place in the top bar: the tab bar holds it too. */
function topLink(name: string): HTMLElement {
  const link = screen.getAllByRole("link", { name })[0];
  if (link === undefined) {
    throw new Error(`no link named ${name}`);
  }
  return link;
}

describe("the start report (spec R1 §4)", () => {
  /** The mock with a count of the start reports and the day reads. */
  function counting(overrides: Partial<Api> = {}): {
    api: Api;
    count: { starts: number; dayReads: number };
  } {
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const count = { starts: 0, dayReads: 0 };
    const api: Api = {
      ...mock,
      getDay: () => {
        count.dayReads += 1;
        return mock.getDay();
      },
      startDay: () => {
        count.starts += 1;
        return mock.startDay();
      },
      ...overrides,
    };
    return { api, count };
  }

  it("goes out one time when the drawing screen shows the open day", async () => {
    const { api, count } = counting();
    renderAt("/today", api);
    await screen.findByText(REVIEW);
    await waitFor(() => expect(count.starts).toBe(1));
    // A new render of the open day sends nothing.
    await typeWord("cold");
    await openReview();
    fireEvent.click(screen.getByText("Keep editing"));
    expect(count.starts).toBe(1);
  });

  it("does not go out again on a refocus or a second visit", async () => {
    const { api, count } = counting();
    renderAt("/today", api);
    await screen.findByText(REVIEW);
    await waitFor(() => expect(count.starts).toBe(1));
    // The tab comes back: the day is read again, and no start is sent.
    const reads = count.dayReads;
    window.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(count.dayReads).toBeGreaterThan(reads));
    await screen.findByText(REVIEW);
    expect(count.starts).toBe(1);
    // The player leaves the drawing screen and comes back.
    fireEvent.click(topLink("Home"));
    await screen.findByText(/Today's photo is hidden/);
    fireEvent.click(topLink("Today"));
    await screen.findByText(REVIEW);
    expect(count.starts).toBe(1);
  });

  it("does not go out from the home screen", async () => {
    const { api, count } = counting();
    renderAt("/", api);
    await screen.findByRole("link", { name: "Start today's session" });
    expect(count.starts).toBe(0);
  });

  it("does not go out for a day that is not open, or that is sent", async () => {
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const cases: Array<[Partial<Api>, RegExp]> = [
      [
        { getDay: async () => ({ ...(await mock.getDay()), submitted: true }) },
        /you're in for today/,
      ],
      [
        {
          getDay: async () => ({ ...(await mock.getDay()), status: "closing" }),
        },
        /Today's session has closed/,
      ],
      [
        {
          getDay: async () => ({ ...(await mock.getDay()), status: "closed" }),
        },
        /Today's session has closed/,
      ],
      [
        {
          getDay: async () => ({
            ...(await mock.getDay()),
            status: "revealed",
          }),
        },
        /You beat \d+% of the photos/,
      ],
      [
        {
          getDay: () =>
            Promise.reject(new ApiError(404, undefined, "no day open")),
        },
        /No session is open right now/,
      ],
    ];
    for (const [overrides, shown] of cases) {
      const { api, count } = counting(overrides);
      const view = renderAt("/today", api);
      expect(await view.findAllByText(shown)).not.toHaveLength(0);
      expect(count.starts).toBe(0);
      view.unmount();
    }
  });

  it("leaves the drawing screen as it is when the report fails", async () => {
    const sent: WireRecord[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const { api, count } = counting({
      startDay: () => {
        count.starts += 1;
        return Promise.reject(new ApiError(0));
      },
      submit: (day, record) => {
        sent.push(record);
        return mock.submit(day, record);
      },
    });
    renderAt("/today", api);
    await screen.findByText(REVIEW);
    await waitFor(() => expect(count.starts).toBe(1));
    // No error shows, and the send works.
    expect(screen.queryByRole("alert")).toBeNull();
    await typeWord("cold");
    fireEvent.click(await openReview());
    await screen.findByText(/you're in for today/);
    expect(sent[0]?.impressions).toEqual(["cold"]);
    // A failed report is not sent a second time.
    expect(count.starts).toBe(1);
  });
});
