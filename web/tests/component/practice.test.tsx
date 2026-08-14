import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
});
