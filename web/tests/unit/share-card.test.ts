import { describe, expect, it } from "vitest";

import {
  CARD_HEIGHT,
  CARD_WIDTH,
  shareCard,
  sketchCard,
} from "../../src/share/card";
import type { CardContext, CardStroke } from "../../src/share/draw";
import { drawShareCard, drawSketchCard } from "../../src/share/draw";

const RESULT = {
  day: "2026-12-01",
  dateLine: "Mon, Nov 30",
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
    // The file name holds the day label, and the card the day's name in
    // the player's own zone, which the caller gives.
    expect(card.fileName).toBe("starvector-2026-12-01.png");
    expect(card.dateLine).toBe("Mon, Nov 30");
    expect(card.shareText).toContain("Mon, Nov 30");
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

describe("the card of a sketch, before the reveal (spec SS1 §6)", () => {
  const SHARE = {
    day: "2026-12-01",
    dateLine: "Mon, Nov 30",
    player: "night-owl",
    host: "starvector.example",
    postClose: true,
  };
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

  it("names the day, the player, and when the photo comes", () => {
    const card = sketchCard(SHARE);
    // A JPEG, with the day label in its name.
    expect(card.fileName).toBe("starvector-sketch-2026-12-01.jpg");
    expect(card.dateLine).toBe("Mon, Nov 30");
    expect(card.noteLine).toBe("The photo is picked after the day closes.");
    expect(card.byLine).toBe("night-owl");
    expect(card.siteLine).toBe("starvector.example");
    expect(card.shareText).toBe(
      "My sketch for Starvector, Mon, Nov 30. The photo is picked after the day closes.",
    );
    expect(card.altText).toBe(
      "A sketch by night-owl for Starvector, Mon, Nov 30. The photo is picked after the day closes.",
    );
  });

  it("says the photo is revealed on a day with the pick at the open", () => {
    const card = sketchCard({ ...SHARE, postClose: false });
    expect(card.noteLine).toBe("The photo is revealed when the day closes.");
  });

  it("holds no result: no percent, no code, and no rank", () => {
    for (const postClose of [true, false]) {
      const card = sketchCard({ ...SHARE, postClose, player: null });
      expect(card.byLine).toBeNull();
      const words = Object.values(card).join(" ");
      expect(words).not.toMatch(/%|\bCode\b|closest|beat|guessing/i);
      expect(Object.keys(card).sort()).toEqual([
        "altText",
        "byLine",
        "dateLine",
        "fileName",
        "noteLine",
        "shareText",
        "siteLine",
      ]);
    }
  });

  it("draws the ground first, then the brand, the sketch, and the lines", () => {
    const card = sketchCard(SHARE);
    const { context, seen } = recorder();
    drawSketchCard(context, card, strokes);
    // A JPEG has no clear pixel: the ground covers the full image.
    expect(seen.rects[0]).toEqual({
      x: 0,
      y: 0,
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
    });
    const texts = seen.texts.map((entry) => entry.text);
    expect(texts).toEqual([
      "Starvector",
      "Mon, Nov 30",
      "The photo is picked after the day closes.",
      "night-owl",
      "starvector.example",
    ]);
    // The sketch, with the color of each stroke.
    expect(seen.strokeColors).toContain("#bf616a");
    expect(seen.strokeColors).toContain("#eceff4");
    const plain = recorder();
    drawSketchCard(plain.context, card, []);
    expect(seen.lineTos).toBeGreaterThan(plain.seen.lineTos);
  });

  it("leaves the result card as it was", () => {
    // The two cards share the frame and the last line: the result card
    // keeps each of its lines.
    const card = shareCard(RESULT);
    const { context, seen } = recorder();
    drawShareCard(context, card, strokes);
    const texts = seen.texts.map((entry) => entry.text);
    expect(texts[0]).toBe("Starvector");
    expect(texts).toContain("Code DCAAYC");
    expect(texts[texts.length - 1]).toBe("starvector.example");
  });
});
