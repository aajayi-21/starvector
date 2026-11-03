import { describe, expect, it } from "vitest";

import { sendBlock, sendBlockHint } from "../../src/intake/send-gate";
import { formatCloseMoment, skillAsPercent } from "../../src/ui/format";

describe("the send gate", () => {
  it("mirrors the Layer 0 stroke floor", () => {
    expect(sendBlock(0, false, 2)).toBe("empty");
    expect(sendBlock(0, true, 2)).toBeNull();
    expect(sendBlock(1, false, 2)).toBe("too-few-strokes");
    expect(sendBlock(1, true, 2)).toBe("too-few-strokes");
    expect(sendBlock(2, false, 2)).toBeNull();
  });

  it("takes the floor from the server", () => {
    expect(sendBlock(2, false, 3)).toBe("too-few-strokes");
    expect(sendBlockHint("too-few-strokes", 3)).toMatch(/at least 3 strokes/);
    expect(sendBlockHint(null, 3)).toBe("");
  });
});

describe("the skill number as an average", () => {
  it("puts chance at 50%", () => {
    expect(skillAsPercent(1)).toBe(50);
    expect(skillAsPercent(2)).toBe(67);
    expect(skillAsPercent(0.5)).toBe(33);
  });
});

describe("the close moment", () => {
  it("reads nothing with no instant", () => {
    expect(formatCloseMoment(null)).toBeNull();
    expect(formatCloseMoment(undefined)).toBeNull();
    expect(formatCloseMoment("not a time")).toBeNull();
  });

  it("names the close in the reader's zone", () => {
    expect(formatCloseMoment("2026-08-14T22:00:00+00:00")).toMatch(/^closes /);
  });
});
