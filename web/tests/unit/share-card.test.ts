import { describe, expect, it } from "vitest";

import { CARD_HEIGHT, CARD_WIDTH, shareCard } from "../../src/share/card";
import type { CardContext, CardStroke } from "../../src/share/draw";
import { drawShareCard } from "../../src/share/draw";

const RESULT = {
  day: "2026-12-01",
  trialCode: "DCAAYC",
  p: 0.8765,
  targetRank: 172,
  decoyCount: 1392,
  player: "night-owl",
  host: "starvector.example",
};

describe("the share card of a result", () => {
  it("states the result against chance in the player's words", () => {
    const card = shareCard(RESULT);
    expect(card.fileName).toBe("starvector-2026-12-01.png");
    expect(card.percentText).toBe("87%");
    expect(card.captionLine).toBe("of the other photos beaten");
    expect(card.placeValue).toBe("172nd");
    expect(card.placeTail).toBe("closest match of 1,393");
    expect(card.codeLine).toBe("Code DCAAYC");
    expect(card.byLine).toBe("night-owl");
    expect(card.siteLine).toBe("starvector.example");
    expect(card.chanceLabel).toContain("50%");
    expect(card.shareText).toContain("I beat 87% of the photos");
    expect(card.shareText).toContain("Guessing averages 50%");
    expect(card.altText).toContain("172nd-closest match of 1,393");
  });

  it("rounds the percent down, as each screen does", () => {
    expect(shareCard({ ...RESULT, p: 0.999 }).percentText).toBe("99%");
    expect(shareCard({ ...RESULT, p: 1 }).percentText).toBe("100%");
    expect(shareCard({ ...RESULT, p: 0 }).percentText).toBe("0%");
  });

  it("grades nothing", () => {
    // Spec M1 §9: a result is stated against chance. No praise and no
    // verdict, for a high result and for a low one.
    for (const p of [0.02, 0.5, 0.98]) {
      const card = shareCard({ ...RESULT, p });
      const words = [
        card.captionLine,
        card.placeLead,
        card.placeTail,
        card.shareText,
        card.altText,
      ]
        .join(" ")
        .toLowerCase();
      for (const verdict of ["good", "great", "bad", "match!", "psychic"]) {
        expect(words).not.toContain(verdict);
      }
    }
  });

  it("leaves out the lines it has no value for", () => {
    const card = shareCard({ ...RESULT, trialCode: null, player: null });
    expect(card.codeLine).toBeNull();
    expect(card.byLine).toBeNull();
  });
});

interface Recorded {
  texts: Array<{ text: string; x: number; align: string }>;
  rects: Array<{ x: number; y: number; width: number; height: number }>;
  lineTos: number;
  strokeColors: string[];
}

function recorder(): { context: CardContext; seen: Recorded } {
  const seen: Recorded = { texts: [], rects: [], lineTos: 0, strokeColors: [] };
  const state: Record<string, unknown> = { textAlign: "left" };
  const calls: Record<string, (...values: never[]) => unknown> = {
    fillText: (text: string, x: number) => {
      seen.texts.push({ text, x, align: String(state.textAlign) });
    },
    fillRect: (x: number, y: number, width: number, height: number) => {
      seen.rects.push({ x, y, width, height });
    },
    lineTo: () => {
      seen.lineTos += 1;
    },
    stroke: () => {
      seen.strokeColors.push(String(state.strokeStyle));
    },
    measureText: () => ({ width: 0 }),
  };
  const context = new Proxy(state, {
    get: (target, name: string) =>
      name in calls ? calls[name] : name in target ? target[name] : () => {},
    set: (target, name: string, value) => {
      target[name] = value;
      return true;
    },
  }) as unknown as CardContext;
  return { context, seen };
}

describe("the drawing of the share card", () => {
  const strokes: CardStroke[] = [
    {
      points: [
        [0.1, 0.1],
        [0.5, 0.5],
        [0.9, 0.2],
      ],
    },
    { points: [[0.3, 0.8]], color: "#bf616a" },
  ];

  it("draws each line of the card", () => {
    const card = shareCard(RESULT);
    const { context, seen } = recorder();
    drawShareCard(context, card, strokes);
    const texts = seen.texts.map((entry) => entry.text);
    for (const line of [
      "Starvector",
      card.dateLine,
      "Code DCAAYC",
      "87%",
      card.captionLine,
      card.chanceLabel,
      "0%",
      "100%",
      card.placeLead,
      "172nd",
      card.placeTail,
      "night-owl",
      "starvector.example",
    ]) {
      expect(texts).toContain(line);
    }
    // The ground covers the full image.
    expect(seen.rects[0]).toEqual({
      x: 0,
      y: 0,
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
    });
  });

  it("fills the bar to the percent", () => {
    const { context, seen } = recorder();
    drawShareCard(context, shareCard({ ...RESULT, p: 0.25 }), []);
    const inner = CARD_WIDTH - 144;
    expect(
      seen.rects.some((rect) => Math.abs(rect.width - inner * 0.25) < 0.01),
    ).toBe(true);
    const none = recorder();
    drawShareCard(none.context, shareCard({ ...RESULT, p: 0 }), []);
    expect(none.seen.rects.some((rect) => rect.width === 0)).toBe(false);
  });

  it("draws the player's sketch with its colors", () => {
    const { context, seen } = recorder();
    drawShareCard(context, shareCard(RESULT), strokes);
    expect(seen.strokeColors).toContain("#bf616a");
    expect(seen.strokeColors).toContain("#eceff4");
    const plain = recorder();
    drawShareCard(plain.context, shareCard(RESULT), []);
    // The sketch adds the line segments of its strokes.
    expect(seen.lineTos).toBeGreaterThan(plain.seen.lineTos);
  });

  it("puts the place in the middle of a card with no sketch", () => {
    const card = shareCard(RESULT);
    const withSketch = recorder();
    drawShareCard(withSketch.context, card, strokes);
    const without = recorder();
    drawShareCard(without.context, card, []);
    const place = (seen: Recorded) =>
      seen.texts.find((entry) => entry.text === "172nd");
    expect(place(without.seen)).toMatchObject({
      x: CARD_WIDTH / 2,
      align: "center",
    });
    expect(place(withSketch.seen)?.align).toBe("left");
    // A stroke with no point is not a sketch.
    const empty = recorder();
    drawShareCard(empty.context, card, [{ points: [] }]);
    expect(place(empty.seen)?.align).toBe("center");
  });
});
