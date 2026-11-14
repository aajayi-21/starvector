import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EpigraphFigure } from "../../src/screens/epigraph-figure";
import type { Epigraph } from "../../src/screens/epigraphs";
import { ResolveText } from "../../src/ui/resolve-text";
import { renderAt } from "./harness";

const THREE: Epigraph[] = ["alpha", "bravo", "charlie"].map((text) => ({
  text,
  author: `author ${text}`,
  work: "work",
  source: "https://example.test/",
}));

function shown(): string {
  return (
    screen
      .getByTestId("epigraph")
      .querySelector("blockquote")
      ?.querySelector(".visually-hidden")?.textContent ?? ""
  );
}

describe("the resolve text (spec H1 §5)", () => {
  it("keeps the whole text for assistive technology", () => {
    const view = render(<ResolveText text="Good morning" random={() => 0.5} />);
    expect(view.container.querySelector(".visually-hidden")?.textContent).toBe(
      "Good morning",
    );
    const letters = view.container.querySelector("[aria-hidden='true']");
    expect(letters?.textContent).toBe("Good morning");
  });

  it("gives the same delays for the same generator", () => {
    const delays = (): string[] => {
      const view = render(<ResolveText text="abc" random={() => 0.5} />);
      const list = Array.from(
        view.container.querySelectorAll<HTMLElement>(".resolve-letter"),
      ).map((el) => el.style.getPropertyValue("--resolve-delay"));
      view.unmount();
      return list;
    };
    expect(delays()).toEqual(delays());
  });
});

describe("the home heading (spec H1 §5)", () => {
  it("holds the greeting and the username as one heading", async () => {
    renderAt("/");
    const heading = await screen.findByRole("heading", { level: 1 });
    await vi.waitFor(() => expect(heading.textContent ?? "").toMatch(/, \w+/));
    expect(
      /^(Good (morning|afternoon|evening)|Welcome back|Ready to view), /.test(
        heading.querySelectorAll(".visually-hidden")[0]?.textContent +
          (heading.querySelectorAll(".visually-hidden")[1]?.textContent ?? ""),
      ),
    ).toBe(true);
  });
});

describe("the epigraph figure (spec H1 §5)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("starts on the drawn epigraph and holds its attribution", () => {
    render(<EpigraphFigure epigraphs={THREE} random={() => 0} />);
    expect(shown()).toBe("alpha");
    expect(screen.getByText("work")).toBeDefined();
  });

  it("moves to a different epigraph after the interval", () => {
    render(
      <EpigraphFigure epigraphs={THREE} random={() => 0} intervalMs={12_000} />,
    );
    act(() => {
      vi.advanceTimersByTime(11_999);
    });
    expect(shown()).toBe("alpha");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(shown()).not.toBe("alpha");
  });

  it("does not move while the tab is hidden", () => {
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    render(<EpigraphFigure epigraphs={THREE} random={() => 0} />);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(shown()).toBe("alpha");
  });

  it("does not move when the player asks for reduced motion", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    render(<EpigraphFigure epigraphs={THREE} random={() => 0} />);
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(shown()).toBe("alpha");
  });
});
