import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import { HARNESS_TODAY, renderAt } from "./harness";

describe("the History screen", () => {
  it("renders the skill hero and stat cards from the mock", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    renderAt("/history");
    expect(
      await screen.findByText(view.skill?.theta.toFixed(3) as string),
    ).toBeDefined();
    expect(screen.getByText("Skill number")).toBeDefined();
    expect(screen.getByText(`${view.days.length}`)).toBeDefined();
    expect(screen.getByText(/shrunk /)).toBeDefined();
  });

  it("lists the revealed days with report links", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    renderAt("/history");
    await screen.findByText("Revealed days");
    const first = view.days[0];
    expect(first).toBeDefined();
    expect(screen.getByText(first?.day as string)).toBeDefined();
    const links = screen.getAllByText("report");
    expect(links).toHaveLength(view.days.length);
    expect((links[0] as HTMLAnchorElement).href).toContain(
      `/reveal?day=${first?.day}`,
    );
  });
});
