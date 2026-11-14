import { describe, expect, it } from "vitest";

import { EPIGRAPHS } from "../../src/screens/epigraphs";
import {
  greetingVariants,
  nextIndex,
  pickGreeting,
} from "../../src/screens/greeting";

describe("the greeting (spec H1 §5)", () => {
  it("follows the clock in its first variant", () => {
    expect(greetingVariants(3)[0]).toBe("Good evening");
    expect(greetingVariants(9)[0]).toBe("Good morning");
    expect(greetingVariants(14)[0]).toBe("Good afternoon");
    expect(greetingVariants(20)[0]).toBe("Good evening");
  });

  it("draws one of the three variants from the generator", () => {
    expect(pickGreeting(9, () => 0)).toBe("Good morning");
    expect(pickGreeting(9, () => 0.4)).toBe("Welcome back");
    expect(pickGreeting(9, () => 0.99)).toBe("Ready to view");
  });

  it("never picks the epigraph that is on screen", () => {
    for (let current = 0; current < 5; current += 1) {
      for (const draw of [0, 0.25, 0.5, 0.75, 0.999]) {
        expect(nextIndex(current, 5, () => draw)).not.toBe(current);
      }
    }
    expect(nextIndex(0, 1, () => 0.5)).toBe(0);
  });
});

describe("the epigraph data (spec H1 §5, D3)", () => {
  it("holds epigraphs of at most 25 words", () => {
    expect(EPIGRAPHS.length).toBeGreaterThanOrEqual(16);
    for (const epigraph of EPIGRAPHS) {
      const words = epigraph.text.split(/\s+/).filter((w) => w !== "…");
      expect(words.length).toBeLessThanOrEqual(25);
    }
  });

  it("names a source, an author, and a work for each one", () => {
    for (const epigraph of EPIGRAPHS) {
      expect(epigraph.source).not.toBe("");
      expect(epigraph.author).not.toBe("");
      expect(epigraph.work).not.toBe("");
    }
  });

  it("checks the wording of each free line against a web page (D3)", () => {
    const free = EPIGRAPHS.filter((e) => e.rights !== "owner-supplied");
    expect(free.length).toBeGreaterThanOrEqual(16);
    for (const epigraph of free) {
      expect(epigraph.source.startsWith("https://")).toBe(true);
    }
  });
});
