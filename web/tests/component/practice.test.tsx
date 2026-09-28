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
      "Photo from",
    )) as HTMLSelectElement;
    const mockDays = (
      await makeMockApi({ today: HARNESS_TODAY }).getPracticeDays()
    ).days;
    expect(picker.options.length).toBe(mockDays.length);
    expect(picker.options[0]?.value).toBe(mockDays[0]?.day);
    const scoreButton = screen.getByText(
      "Check my practice",
    ) as HTMLButtonElement;
    expect(scoreButton.disabled).toBe(true);
    drawOnCanvas(container);
    expect(scoreButton.disabled).toBe(false);
  });

  it("scores a sketch and renders the result panel", async () => {
    const { container } = renderAt("/practice");
    await screen.findByLabelText("Photo from");
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
    await screen.findByLabelText("Photo from");
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
    await screen.findByLabelText("Photo from");
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
    fireEvent.click(screen.getByText("Pick strokes"));
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
    const label = screen.getByLabelText("Name the picked strokes");
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
