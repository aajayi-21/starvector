import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiContext } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { AvatarCircle } from "../../src/ui/avatar";
import { StreakName } from "../../src/ui/streak-name";
import { HARNESS_TODAY } from "./harness";

function inApi(node: React.ReactNode) {
  return render(
    <ApiContext.Provider value={makeMockApi({ today: HARNESS_TODAY })}>
      {node}
    </ApiContext.Provider>,
  );
}

describe("the avatar ring (spec H1 §4)", () => {
  it("draws the plain circle with no streak or a short one", () => {
    const none = inApi(
      <AvatarCircle player="ade" avatarHash={null} size={34} />,
    );
    expect(none.container.querySelector(".streak-ring")).toBeNull();
    none.unmount();
    const short = inApi(
      <AvatarCircle player="ade" avatarHash={null} size={34} streak={2} />,
    );
    expect(short.container.querySelector(".streak-ring")).toBeNull();
  });

  it.each([
    [3, "1"],
    [7, "2"],
    [30, "3"],
  ])("a streak of %i days draws a tier %s ring", (streak, tier) => {
    const view = inApi(
      <AvatarCircle player="ade" avatarHash={null} size={34} streak={streak} />,
    );
    const ring = view.container.querySelector(".streak-ring");
    expect(ring?.getAttribute("data-tier")).toBe(tier);
  });

  it("keeps the outer size of the plain circle", () => {
    const view = inApi(
      <AvatarCircle player="ade" avatarHash={null} size={34} streak={30} />,
    );
    const ring = view.container.querySelector<HTMLElement>(".streak-ring");
    expect(ring?.style.width).toBe("34px");
    expect(ring?.style.height).toBe("34px");
    // Ring 2 and gap 2 on each side leave a 26 px picture.
    const picture = view.container.querySelector<HTMLElement>(
      ".streak-ring-gap > span",
    );
    expect(picture?.style.width).toBe("26px");
  });
});

describe("the marked username (spec H1 §4)", () => {
  it("adds the hidden streak label from tier 1", () => {
    inApi(<StreakName streak={3}>ade</StreakName>);
    expect(screen.getByText(/3-day streak/).className).toBe("visually-hidden");
  });

  it("draws the plain text below tier 1", () => {
    const view = inApi(<StreakName streak={2}>ade</StreakName>);
    expect(view.container.querySelector(".streak-name")).toBeNull();
    expect(view.container.textContent).toBe("ade");
  });
});
