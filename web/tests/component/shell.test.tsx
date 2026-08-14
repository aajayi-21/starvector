import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderAt } from "./harness";

describe("the shell", () => {
  it("renders the nav with the streak tag from /api/me", async () => {
    renderAt("/");
    expect(await screen.findByText("Starvector")).toBeDefined();
    expect(await screen.findByText(/streak/)).toBeDefined();
    expect(screen.getByText("Today")).toBeDefined();
    expect(screen.getByText("Practice")).toBeDefined();
    expect(screen.getByText("History")).toBeDefined();
    expect(screen.getByText("Leaderboard")).toBeDefined();
  });

  it("renders each screen at its path", async () => {
    const paths: Array<[string, RegExp]> = [
      ["/", /Today's target/],
      ["/practice", /Practice/],
      ["/history", /History/],
      ["/reveal", /Reveal|Leaderboard/],
    ];
    for (const [path, expected] of paths) {
      const view = renderAt(path);
      expect(await view.findAllByText(expected)).not.toHaveLength(0);
      view.unmount();
    }
  });
});
