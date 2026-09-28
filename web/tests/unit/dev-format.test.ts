import { describe, expect, it } from "vitest";
import { relative, utcStamp } from "../../src/dev/format";
import { toCsv } from "../../src/dev/index-tab";
import { stepText } from "../../src/dev/schedule-tab";

describe("the console's formatting", () => {
  it("writes UTC stamps and distances", () => {
    expect(utcStamp("2026-09-24T22:00:00+00:00")).toBe("2026-09-24 22:00 UTC");
    expect(utcStamp("2026-09-24T23:30:00+01:00")).toBe("2026-09-24 22:30 UTC");
    expect(utcStamp(null)).toBe("—");
    const now = Date.parse("2026-09-24T20:00:00Z");
    expect(relative("2026-09-24T22:30:00Z", now)).toBe("in 2 h 30 min");
    expect(relative("2026-09-24T19:50:00Z", now)).toBe("10 min ago");
    expect(relative("2026-09-24T20:00:20Z", now)).toBe("now");
  });

  it("names each rollover step in words", () => {
    expect(stepText("close", "2026-09-24", null)).toBe(
      "Close 2026-09-24 and score it",
    );
    expect(stepText("reveal", "2026-09-24", null)).toBe("Reveal 2026-09-24");
    expect(stepText("open", null, "2026-09-25")).toBe("Open 2026-09-25");
  });

  it("quotes CSV cells that hold a comma, a quote, or a line break", () => {
    expect(
      toCsv({
        columns: ["a", "b"],
        rows: [
          ["x, y", 'say "hi"'],
          [null, 3],
          ["two\nlines", 0.5],
        ],
        truncated: false,
        elapsed_ms: 1,
      }),
    ).toBe('a,b\r\n"x, y","say ""hi"""\r\n,3\r\n"two\nlines",0.5\r\n');
  });
});
