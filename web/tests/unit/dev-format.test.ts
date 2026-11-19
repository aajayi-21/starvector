import { describe, expect, it } from "vitest";
import { sentenceCase } from "../../src/dev/controls";
import { relative, utcDate, utcStamp, utcTime } from "../../src/dev/format";
import { toCsv } from "../../src/dev/index-tab";
import { dueSentence, stepText } from "../../src/dev/schedule-tab";
import {
  dayProtocol,
  dayStages,
  isPicked,
  pickSentence,
} from "../../src/dev/stages";

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

describe("the console's labels", () => {
  it("splits a stamp into its time and its date", () => {
    expect(utcTime("2026-09-24T22:04:00+00:00")).toBe("22:04 UTC");
    expect(utcDate("2026-09-24T23:30:00+01:00")).toBe("2026-09-24");
    expect(utcTime(null)).toBe("—");
    expect(utcDate(undefined)).toBe("—");
  });

  it("writes a wire value in sentence case", () => {
    expect(sentenceCase("open")).toBe("Open");
    expect(sentenceCase("nothing due")).toBe("Nothing due");
    expect(sentenceCase("")).toBe("");
  });

  it("writes the due steps as one sentence", () => {
    expect(
      dueSentence(
        {
          at: "2026-09-24T22:00:00+00:00",
          steps: ["close", "reveal", "open"],
          opens: "2026-09-25",
        },
        "2026-09-24",
      ),
    ).toBe(
      "Close 2026-09-24 and score it, then reveal 2026-09-24, then open 2026-09-25",
    );
    expect(
      dueSentence(
        { at: "2026-09-24T22:00:00+00:00", steps: [], opens: null },
        "2026-09-24",
      ),
    ).toBe("");
  });
});

describe("the stages of a day", () => {
  const states = (
    ...args: Parameters<typeof dayStages>
  ): Array<[string, string]> =>
    dayStages(...args).map((stage) => [stage.id, stage.state]);

  it("reads the protocol from the commitment (spec VP1 §6)", () => {
    expect(dayProtocol("c".repeat(64))).toBe("commit-v1");
    expect(dayProtocol(null)).toBe("vp1");
    expect(dayProtocol("")).toBe("vp1");
    expect(isPicked("t".repeat(64))).toBe(true);
    expect(isPicked(null)).toBe(false);
    expect(isPicked("")).toBe(false);
  });

  it("gives a commit-v1 day three stages, with no pick", () => {
    expect(states("commit-v1", "open", true)).toEqual([
      ["opened", "done"],
      ["close", "current"],
      ["reveal", "pending"],
    ]);
    expect(states("commit-v1", "closing", true)).toEqual([
      ["opened", "done"],
      ["close", "current"],
      ["reveal", "pending"],
    ]);
    expect(states("commit-v1", "closed", true)).toEqual([
      ["opened", "done"],
      ["close", "done"],
      ["reveal", "current"],
    ]);
    expect(states("commit-v1", "revealed", true)).toEqual([
      ["opened", "done"],
      ["close", "done"],
      ["reveal", "done"],
    ]);
  });

  it("gives a vp1 day the pick between the close and the reveal", () => {
    expect(states("vp1", "open", false)).toEqual([
      ["opened", "done"],
      ["close", "current"],
      ["pick", "pending"],
      ["reveal", "pending"],
    ]);
    // A close that stopped after the pick: the pick is done and the
    // close is not.
    expect(states("vp1", "closing", true)).toEqual([
      ["opened", "done"],
      ["close", "current"],
      ["pick", "done"],
      ["reveal", "pending"],
    ]);
    expect(states("vp1", "closing", false)).toEqual([
      ["opened", "done"],
      ["close", "current"],
      ["pick", "pending"],
      ["reveal", "pending"],
    ]);
    expect(states("vp1", "closed", true)).toEqual([
      ["opened", "done"],
      ["close", "done"],
      ["pick", "done"],
      ["reveal", "current"],
    ]);
    expect(states("vp1", "revealed", true)).toEqual([
      ["opened", "done"],
      ["close", "done"],
      ["pick", "done"],
      ["reveal", "done"],
    ]);
  });

  it("names the stages in the words of the track", () => {
    expect(dayStages("vp1", "open", false).map((stage) => stage.label)).toEqual(
      ["Opened", "Close and score", "Pick photo", "Reveal"],
    );
    expect(
      dayStages("commit-v1", "open", true).map((stage) => stage.label),
    ).toEqual(["Opened", "Close and score", "Reveal"]);
  });

  it("says when the photo of each protocol is picked", () => {
    expect(pickSentence("vp1")).toMatch(/after the close/);
    expect(pickSentence("commit-v1")).toMatch(/when it opened/);
  });
});
