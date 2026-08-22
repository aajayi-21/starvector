import { describe, expect, it } from "vitest";

import { AVATAR_MAX_PX, scaledBox } from "../../src/ui/downscale";

describe("the avatar downscale box (spec A1, D2)", () => {
  it("caps the longest side and keeps the ratio", () => {
    expect(scaledBox(1024, 768)).toEqual({ width: 256, height: 192 });
    expect(scaledBox(768, 1024)).toEqual({ width: 192, height: 256 });
    expect(AVATAR_MAX_PX).toBe(256);
  });

  it("does not upscale a small image", () => {
    expect(scaledBox(100, 60)).toEqual({ width: 100, height: 60 });
    expect(scaledBox(256, 256)).toEqual({ width: 256, height: 256 });
  });

  it("never rounds a side to zero", () => {
    expect(scaledBox(10000, 1)).toEqual({ width: 256, height: 1 });
  });
});
