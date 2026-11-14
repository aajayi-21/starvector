import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EpigraphFigure } from "../../src/screens/epigraph-figure";
import type { Epigraph } from "../../src/screens/epigraphs";
import { ResolveText } from "../../src/ui/resolve-text";
import { renderAt } from "./harness";

const THREE: Epigraph[] = ["alpha", "bravo", "charlie"].map((text) => ({
  text,
  rights: "public-domain",
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
  it("names the greeting and the username as one heading", async () => {
    renderAt("/");
    // The accessible name reads the hidden copies alone: the animated
    // letters are aria-hidden, so the name holds each word one time.
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: /^(Good (morning|afternoon|evening)|Welcome back|Ready to view), \S+$/,
      }),
    ).toBeDefined();
  });
});

describe("the epigraph figure (spec H1 §5)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    // The hidden-tab test spies on visibilityState; without this the
    // tests after it run with the tab still hidden and prove nothing.
    vi.restoreAllMocks();
  });

  it("starts on the drawn epigraph and holds its attribution", () => {
    render(<EpigraphFigure epigraphs={THREE} random={() => 0} />);
    expect(shown()).toBe("alpha");
    expect(
      screen.getByTestId("epigraph").querySelector("figcaption")?.textContent,
    ).toBe("author alpha, work");
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
    expect(screen.queryByRole("button")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(shown()).toBe("alpha");
  });

  it("stops when reduced motion turns on during the visit", () => {
    let listener: (() => void) | null = null;
    const query = {
      matches: false,
      media: "",
      addEventListener: (_: string, fn: () => void) => {
        listener = fn;
      },
      removeEventListener: () => undefined,
    };
    vi.stubGlobal("matchMedia", () => query);
    render(<EpigraphFigure epigraphs={THREE} random={() => 0} />);
    act(() => {
      query.matches = true;
      listener?.();
    });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(shown()).toBe("alpha");
  });

  it("pauses and plays from its control (WCAG 2.2.2)", () => {
    render(<EpigraphFigure epigraphs={THREE} random={() => 0} />);
    act(() => {
      screen.getByRole("button", { name: "Pause the epigraphs" }).click();
    });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(shown()).toBe("alpha");
    act(() => {
      screen.getByRole("button", { name: "Play the epigraphs" }).click();
    });
    act(() => {
      vi.advanceTimersByTime(12_000);
    });
    expect(shown()).not.toBe("alpha");
  });

  it("holds while the pointer is on it", () => {
    const view = render(<EpigraphFigure epigraphs={THREE} random={() => 0} />);
    const frame = view.container.querySelector(".epigraph-frame");
    act(() => {
      frame?.dispatchEvent(new MouseEvent("mouseenter"));
    });
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(shown()).toBe("alpha");
  });

  it("renders the three longest hidden, so the frame fits the tallest", () => {
    const four = [
      ...THREE,
      { ...THREE[0], text: "a much longer line than the other three" },
    ] as Epigraph[];
    const view = render(<EpigraphFigure epigraphs={four} random={() => 0} />);
    const sizers = view.container.querySelectorAll(".epigraph-sizer");
    expect(sizers).toHaveLength(3);
    expect(sizers[0]?.textContent).toContain("a much longer line");
    for (const sizer of sizers) {
      expect(sizer.getAttribute("aria-hidden")).toBe("true");
    }
  });
});
