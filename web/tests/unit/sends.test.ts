import { describe, expect, it } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import type { WireRecord } from "../../src/api/types";
import { ApiError } from "../../src/api/types";
import { sendsGate } from "../../src/ui/send-count";

const TODAY = "2026-08-14";
const SENTINEL = "zq-sentinel";

function recordWithText(): WireRecord {
  return {
    impressions: [`${SENTINEL}-word`],
    canvas_strokes: [
      {
        points: [
          [0.1, 0.2],
          [0.4, 0.5],
        ],
        group_id: "g1",
        color: "#bf616a",
      },
    ],
    groups: [{ id: "g1", label: `${SENTINEL}-label` }],
    relations: [],
    pasted_text: `${SENTINEL}-note`,
  };
}

describe("send, then see: the gate of the sends screen (spec SS1 §4)", () => {
  const open = { day: TODAY, status: "open" as const, submitted: false };

  it("asks a player with no send to send first", () => {
    expect(sendsGate(open, TODAY)).toBe("send-first");
  });

  it("opens the day in play to a player who sent", () => {
    expect(sendsGate({ ...open, submitted: true }, TODAY)).toBe("open");
    expect(
      sendsGate({ ...open, status: "closing", submitted: true }, TODAY),
    ).toBe("open");
  });

  it("keeps a closed day shut for a player with no send, until the reveal", () => {
    expect(sendsGate({ ...open, status: "closing" }, TODAY)).toBe(
      "after-reveal",
    );
    expect(sendsGate({ ...open, status: "closed" }, TODAY)).toBe(
      "after-reveal",
    );
    expect(sendsGate({ ...open, status: "revealed" }, TODAY)).toBe("open");
  });

  it("opens an earlier day, which is revealed", () => {
    expect(sendsGate(open, "2026-08-13")).toBe("open");
  });
});

describe("the mock's sends of a day (spec SS1 §7)", () => {
  it("refuses the open day until the mock player sends", async () => {
    const api = makeMockApi({ today: TODAY });
    await expect(api.getSends(TODAY)).rejects.toMatchObject({ status: 404 });
    await api.submit(TODAY, recordWithText());
    const page = await api.getSends(TODAY);
    expect(page.total).toBe((await api.getDay()).sends);
    // The newest send is first, and it is the caller's own.
    expect(page.entries[0]?.player).toBe((await api.getMe()).player);
  });

  it("gives the sketch of the caller's send and no text of it", async () => {
    const api = makeMockApi({ today: TODAY });
    await api.submit(TODAY, recordWithText());
    const own = (await api.getSends(TODAY)).entries[0];
    expect(own?.strokes).toEqual([
      {
        points: [
          [0.1, 0.2],
          [0.4, 0.5],
        ],
        color: "#bf616a",
      },
    ]);
    let before: number | undefined;
    let text = "";
    do {
      const page = await api.getSends(TODAY, before);
      text += JSON.stringify(page);
      before = page.next_before ?? undefined;
    } while (before !== undefined);
    expect(text).not.toContain(SENTINEL);
    expect(text).not.toContain("group_id");
  });

  it("pages from the newest send to the first", async () => {
    const api = makeMockApi({ today: TODAY, submittedToday: true });
    const names: string[] = [];
    let before: number | undefined;
    let pages = 0;
    do {
      const page = await api.getSends(TODAY, before);
      expect(page.total).toBe(13);
      names.push(...page.entries.map((entry) => entry.player));
      before = page.next_before ?? undefined;
      pages += 1;
    } while (before !== undefined);
    expect(pages).toBe(3);
    expect(names).toHaveLength(13);
    expect(new Set(names).size).toBe(13);
  });

  it("holds a send with no sketch, a withheld one, and a deleted account", async () => {
    const api = makeMockApi({ today: TODAY, submittedToday: true });
    const entries = [];
    let before: number | undefined;
    do {
      const page = await api.getSends(TODAY, before);
      entries.push(...page.entries);
      before = page.next_before ?? undefined;
    } while (before !== undefined);
    const states = new Set(entries.map((entry) => entry.state));
    expect(states).toEqual(new Set(["sketch", "words-only", "withheld"]));
    for (const entry of entries) {
      expect(entry.strokes.length > 0).toBe(entry.state === "sketch");
    }
    const anonymous = entries.filter((entry) => !entry.named);
    expect(anonymous).toHaveLength(1);
    expect(anonymous[0]?.player.startsWith("anon-")).toBe(true);
  });

  it("opens an earlier day with no send of the open day", async () => {
    const api = makeMockApi({ today: TODAY });
    const page = await api.getSends("2026-08-01");
    expect(page.day).toBe("2026-08-01");
    expect(page.entries.length).toBeGreaterThan(0);
  });

  it("refuses a cursor that is not a position", async () => {
    const api = makeMockApi({ today: TODAY, submittedToday: true });
    for (const bad of [-1, 14, 1.5]) {
      await expect(api.getSends(TODAY, bad)).rejects.toBeInstanceOf(ApiError);
    }
  });

  it("gives the caller their own record of the open day after the send", async () => {
    const api = makeMockApi({ today: TODAY });
    await expect(api.getSubmission(TODAY)).rejects.toMatchObject({
      status: 404,
    });
    const record = recordWithText();
    await api.submit(TODAY, record);
    expect((await api.getSubmission(TODAY)).record).toEqual(record);
  });
});
