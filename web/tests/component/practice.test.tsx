import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

function drawOnCanvas(container: HTMLElement): void {
  const live = container.querySelectorAll("canvas")[1];
  if (live === undefined) {
    throw new Error("no live canvas layer");
  }
  for (const [type, x, y] of [
    ["pointerdown", 30, 30],
    ["pointermove", 150, 150],
    ["pointerup", 150, 150],
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
  it("lists revealed days newest first and gates the score button", async () => {
    const { container } = renderAt("/practice");
    const picker = (await screen.findByLabelText(
      "practice day",
    )) as HTMLSelectElement;
    const mockDays = (
      await makeMockApi({ today: HARNESS_TODAY }).getPracticeDays()
    ).days;
    expect(picker.options.length).toBe(mockDays.length);
    expect(picker.options[0]?.value).toBe(mockDays[0]?.day);
    const scoreButton = screen.getByText("Score now") as HTMLButtonElement;
    expect(scoreButton.disabled).toBe(true);
    drawOnCanvas(container);
    expect(scoreButton.disabled).toBe(false);
  });

  it("scores a sketch and renders the result panel", async () => {
    const { container } = renderAt("/practice");
    await screen.findByLabelText("practice day");
    drawOnCanvas(container);
    fireEvent.click(screen.getByText("Score now"));
    const scoreLine = await screen.findByText(/beat \d+ of \d+ decoys/);
    expect(scoreLine.textContent).toMatch(/position \d+ of the full ordering/);
    expect(await screen.findByText("1 scored this session")).toBeDefined();
    const image = (await screen.findByAltText(
      /revealed practice target/,
    )) as HTMLImageElement;
    expect(image.src.startsWith("data:image/svg+xml")).toBe(true);
    expect(screen.getByText("What matched")).toBeDefined();
  });

  it("shows the empty state on the constant 404", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getPracticeDays: () =>
        Promise.reject(new ApiError(404, undefined, "no revealed day")),
    };
    renderAt("/practice", api);
    expect(await screen.findByText(/No revealed day yet/)).toBeDefined();
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
    await screen.findByLabelText("practice day");
    const scoreButton = screen.getByText("Score now") as HTMLButtonElement;
    expect(scoreButton.disabled).toBe(true);
    const input = screen.getByPlaceholderText(/one impression/);
    fireEvent.change(input, { target: { value: "tall structure" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(scoreButton.disabled).toBe(false);
    fireEvent.click(scoreButton);
    await screen.findByText(/beat \d+ of \d+ decoys/);
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
    await screen.findByLabelText("practice day");
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
    fireEvent.click(screen.getByText("Select strokes"));
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
    const label = screen.getByPlaceholderText(/what is it/);
    fireEvent.change(label, { target: { value: "tower" } });
    fireEvent.click(screen.getByText("Group"));
    expect(await screen.findByText("tower")).toBeDefined();
    fireEvent.click(screen.getByText("Score now"));
    await screen.findByText(/beat \d+ of \d+ decoys/);
    expect(sent).toHaveLength(1);
    expect(sent[0]?.[1].groups).toEqual([{ id: "g1", label: "tower" }]);
    expect(sent[0]?.[1].canvas_strokes[0]?.group_id).toBe("g1");
  });
});
