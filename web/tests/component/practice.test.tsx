import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { makeDayNames } from "../../src/ui/day-names";
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

describe("the Practice screen", () => {
  it("opens on the newest day and gates the score button", async () => {
    const { container } = renderAt("/practice");
    const mockDays = (
      await makeMockApi({ today: HARNESS_TODAY }).getPracticeDays()
    ).days;
    const names = makeDayNames("22:00");
    const newest = names.long(mockDays[0]?.day ?? "");
    // The row of days names the newest day, and a step on is today.
    const date = await screen.findByRole("button", {
      name: `Practice · ${newest}`,
    });
    expect(
      (screen.getByLabelText("The day after") as HTMLButtonElement).disabled,
    ).toBe(false);
    // The date opens a calendar with that day pressed.
    fireEvent.click(date);
    const calendar = screen.getByRole("dialog", { name: "Pick a day" });
    expect(
      within(calendar)
        .getByRole("button", { name: newest })
        .getAttribute("aria-pressed"),
    ).toBe("true");
    const scoreButton = screen.getByText(
      "Check my practice",
    ) as HTMLButtonElement;
    expect(scoreButton.disabled).toBe(true);
    drawOnCanvas(container);
    expect(scoreButton.disabled).toBe(false);
  });

  it("goes to the day that the calendar gives", async () => {
    renderAt("/practice");
    const mockDays = (
      await makeMockApi({ today: HARNESS_TODAY }).getPracticeDays()
    ).days;
    const names = makeDayNames("22:00");
    const second = names.long(mockDays[1]?.day ?? "");
    fireEvent.click(
      await screen.findByRole("button", {
        name: `Practice · ${names.long(mockDays[0]?.day ?? "")}`,
      }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Pick a day" })).getByRole(
        "button",
        { name: second },
      ),
    );
    expect(
      await screen.findByRole("button", { name: `Practice · ${second}` }),
    ).toBeDefined();
    // The calendar closes, and the path holds the day.
    expect(screen.queryByRole("dialog", { name: "Pick a day" })).toBeNull();
  });

  it("steps back a day, and forward to today", async () => {
    renderAt("/practice");
    const mockDays = (
      await makeMockApi({ today: HARNESS_TODAY }).getPracticeDays()
    ).days;
    const names = makeDayNames("22:00");
    await screen.findByRole("button", {
      name: `Practice · ${names.long(mockDays[0]?.day ?? "")}`,
    });
    fireEvent.click(screen.getByLabelText("The day before"));
    expect(
      await screen.findByRole("button", {
        name: `Practice · ${names.long(mockDays[1]?.day ?? "")}`,
      }),
    ).toBeDefined();
    fireEvent.click(screen.getByLabelText("The day after"));
    await screen.findByRole("button", {
      name: `Practice · ${names.long(mockDays[0]?.day ?? "")}`,
    });
    fireEvent.click(screen.getByLabelText("The day after"));
    // Today is the last day of the row.
    expect(await screen.findByText("Review and send")).toBeDefined();
  });

  it("scores a sketch and renders the result panel", async () => {
    const { container } = renderAt("/practice");
    await screen.findByText("Check my practice");
    drawOnCanvas(container);
    fireEvent.click(screen.getByText("Check my practice"));
    expect(
      await screen.findByText(/matched this photo better than \d+ of the/),
    ).toBeDefined();
    expect(
      screen.getByText(/Practice isn't saved and doesn't count/),
    ).toBeDefined();
    const image = (await screen.findByAltText(
      /Mock photo/,
    )) as HTMLImageElement;
    expect(image.src.startsWith("data:image/svg+xml")).toBe(true);
    expect(screen.getByText("What connected")).toBeDefined();
    // Back to editing keeps the sketch.
    fireEvent.click(screen.getByText("Edit and check again"));
    expect(
      (screen.getByText("Check my practice") as HTMLButtonElement).disabled,
    ).toBe(false);
  });

  it("shows the empty state on the constant 404", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getPracticeDays: () =>
        Promise.reject(new ApiError(404, undefined, "no revealed day")),
    };
    renderAt("/practice", api);
    expect(
      await screen.findByText(/Practice uses photos from days that are over/),
    ).toBeDefined();
  });

  // The spec A1 §6 growth: the typed intake matches the daily
  // screen — impressions and labeled groups ride the scored record.
  it("scores typed impressions with no strokes", async () => {
    const sent: Array<Parameters<Api["scorePractice"]>> = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      scorePractice: (day, record) => {
        sent.push([day, record]);
        return mock.scorePractice(day, record);
      },
    };
    renderAt("/practice", api);
    await screen.findByText("Check my practice");
    const scoreButton = screen.getByText(
      "Check my practice",
    ) as HTMLButtonElement;
    expect(scoreButton.disabled).toBe(true);
    const input = screen.getByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "tall structure" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(scoreButton.disabled).toBe(false);
    fireEvent.click(scoreButton);
    await screen.findByText(/matched this photo better than/);
    expect(sent).toHaveLength(1);
    expect(sent[0]?.[1].impressions).toEqual(["tall structure"]);
    expect(sent[0]?.[1].canvas_strokes).toEqual([]);
  });

  it("groups selected strokes and serializes the label", async () => {
    const sent: Array<Parameters<Api["scorePractice"]>> = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      scorePractice: (day, record) => {
        sent.push([day, record]);
        return mock.scorePractice(day, record);
      },
    };
    const { container } = renderAt("/practice", api);
    await screen.findByText("Check my practice");
    // jsdom rects are 0x0 and the hit-test is geometric, so the
    // live layer gets a real 300x300 box for this test alone.
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
    drawOnCanvas(container);
    fireEvent.click(screen.getByRole("button", { name: "Label parts" }));
    fireEvent.click(screen.getByText("Pick lines"));
    // The committed stroke passes below the drag's midpoint.
    const pick = new MouseEvent("pointerdown", {
      bubbles: true,
      clientX: 90,
      clientY: 90,
    });
    Object.defineProperties(pick, {
      pointerId: { value: 1 },
      isPrimary: { value: true },
      pointerType: { value: "mouse" },
    });
    fireEvent(live, pick);
    const label = screen.getByLabelText("Name the picked lines");
    fireEvent.change(label, { target: { value: "tower" } });
    fireEvent.click(screen.getByText("Label"));
    expect(await screen.findByText("tower")).toBeDefined();
    fireEvent.click(screen.getByText("Check my practice"));
    await screen.findByText(/matched this photo better than/);
    expect(sent).toHaveLength(1);
    expect(sent[0]?.[1].groups).toEqual([{ id: "g1", label: "tower" }]);
    expect(sent[0]?.[1].canvas_strokes[0]?.group_id).toBe("g1");
  });
});

describe("the practice draft", () => {
  it("comes back after the screen leaves, and Start over clears it", async () => {
    const first = renderAt("/practice");
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "kept word" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("kept word");
    await waitFor(() =>
      expect(window.localStorage.getItem("sv:practice-draft")).toContain(
        "kept word",
      ),
    );
    first.unmount();

    renderAt("/practice");
    expect(await screen.findByText("kept word")).toBeDefined();
    fireEvent.click(screen.getByText("Check my practice"));
    fireEvent.click(await screen.findByText("Start over"));
    await waitFor(() => expect(screen.queryByText("kept word")).toBeNull());
    expect(window.localStorage.getItem("sv:practice-draft")).toBeNull();
  });

  it("includes a word typed and not added", async () => {
    const sent: string[][] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      scorePractice: (day, record) => {
        sent.push(record.impressions);
        return mock.scorePractice(day, record);
      },
    };
    renderAt("/practice", api);
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "typed only" } });
    fireEvent.click(screen.getByText("Check my practice"));
    await screen.findByText(/matched this photo better than/);
    expect(sent).toEqual([["typed only"]]);
  });

  it("explains the practice limit", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      scorePractice: () => Promise.reject(new ApiError(429, "practice-limit")),
    };
    renderAt("/practice", api);
    const input = await screen.findByLabelText("Add a word");
    fireEvent.change(input, { target: { value: "cold" } });
    fireEvent.click(screen.getByText("Check my practice"));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /a lot of practice for one hour/,
    );
  });
});
