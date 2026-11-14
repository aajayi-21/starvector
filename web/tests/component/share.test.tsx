import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { makeMockApi } from "../../src/api/mock";
import type { ShareCard } from "../../src/share/card";
import type { CardStroke } from "../../src/share/draw";
import * as share from "../../src/share/share";
import { HARNESS_TODAY, renderAt } from "./harness";

const made: Array<{ card: ShareCard; strokes: ReadonlyArray<CardStroke> }> = [];

beforeEach(() => {
  made.length = 0;
  vi.spyOn(share, "renderShareImage").mockImplementation(
    async (card, strokes) => {
      made.push({ card, strokes });
      return new Blob(["png"], { type: "image/png" });
    },
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function historyTable(): Promise<HTMLElement> {
  return (await screen.findByText("Every day")).closest(
    "section",
  ) as HTMLElement;
}

describe("the share control of a result", () => {
  it("is on each day of the results table", async () => {
    const view = await makeMockApi({ today: HARNESS_TODAY }).getHistory();
    renderAt("/history");
    const buttons = within(await historyTable()).getAllByRole("button", {
      name: /^Share the result of .* as an image$/,
    });
    expect(buttons).toHaveLength(view.days.length);
  });

  it("makes the image of that day and saves it", async () => {
    const deliver = vi
      .spyOn(share, "deliverShareImage")
      .mockResolvedValue("saved");
    const api = makeMockApi({ today: HARNESS_TODAY });
    const view = await api.getHistory();
    const row = view.days[0];
    if (row === undefined) {
      throw new Error("the mock has no played day");
    }
    renderAt("/history", api);
    const table = await historyTable();
    const button = within(table).getAllByRole("button", {
      name: /^Share the result of /,
    })[0] as HTMLButtonElement;
    fireEvent.click(button);
    await waitFor(() => expect(deliver).toHaveBeenCalledTimes(1));
    const { card } = made[0] as (typeof made)[number];
    expect(card.fileName).toBe(`starvector-${row.day}.png`);
    expect(card.codeLine).toBe(`Code ${row.trial_code}`);
    expect(card.percentText).toBe(`${Math.floor(row.p * 100 + 1e-9)}%`);
    expect(card.byLine).toBe((await api.getMe()).player);
    expect(await within(table).findByText("Image saved.")).toBeDefined();
    expect(button.disabled).toBe(false);
  });

  it("says nothing when the player closes the share sheet", async () => {
    vi.spyOn(share, "deliverShareImage").mockResolvedValue("cancelled");
    renderAt("/history");
    const table = await historyTable();
    fireEvent.click(
      within(table).getAllByRole("button", {
        name: /^Share the result of /,
      })[0] as HTMLButtonElement,
    );
    await waitFor(() => expect(made).toHaveLength(1));
    await waitFor(() =>
      expect(within(table).queryByText("Making the image…")).toBeNull(),
    );
    expect(within(table).queryByText("Image saved.")).toBeNull();
    expect(within(table).queryByText("Shared.")).toBeNull();
  });

  it("says so when the image cannot be made", async () => {
    vi.spyOn(share, "renderShareImage").mockRejectedValue(
      new Error("no canvas"),
    );
    renderAt("/history");
    const table = await historyTable();
    fireEvent.click(
      within(table).getAllByRole("button", {
        name: /^Share the result of /,
      })[0] as HTMLButtonElement,
    );
    expect(
      await within(table).findByText("Couldn't make the image. Try again."),
    ).toBeDefined();
  });

  it("is on the results screen of a day, with the sketch", async () => {
    const deliver = vi
      .spyOn(share, "deliverShareImage")
      .mockResolvedValue("shared");
    const api = makeMockApi({ today: HARNESS_TODAY });
    const day = (await api.getHistory()).days[0]?.day as string;
    renderAt(`/reveal?day=${day}`, api);
    const button = await screen.findByRole("button", {
      name: /^Share the result of .* as an image$/,
    });
    expect(button.textContent).toContain("Share");
    fireEvent.click(button);
    await waitFor(() => expect(deliver).toHaveBeenCalledTimes(1));
    const { card, strokes } = made[0] as (typeof made)[number];
    expect(card.fileName).toBe(`starvector-${day}.png`);
    // The code comes from the results list, which this screen does not show.
    expect(card.codeLine).toMatch(/^Code [A-Z0-9]{6}$/);
    const stored = await api.getSubmission(day);
    expect(strokes).toEqual(stored.record.canvas_strokes);
    expect(await screen.findByText("Shared.")).toBeDefined();
  });
});

describe("giving the image to the device", () => {
  const card = { fileName: "starvector-2026-12-01.png", shareText: "x" };

  afterEach(() => {
    Reflect.deleteProperty(navigator, "share");
    Reflect.deleteProperty(navigator, "canShare");
  });

  function stubShare(
    canShare: boolean,
    shareImpl: () => Promise<void>,
  ): ReturnType<typeof vi.fn> {
    const spy = vi.fn(shareImpl);
    Object.defineProperty(navigator, "share", {
      configurable: true,
      value: spy,
    });
    Object.defineProperty(navigator, "canShare", {
      configurable: true,
      value: () => canShare,
    });
    return spy;
  }

  function stubDownload(): { clicks: string[] } {
    const clicks: string[] = [];
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: () => "blob:test",
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: () => undefined,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
      function click(this: HTMLAnchorElement) {
        clicks.push(this.download);
      },
    );
    return { clicks };
  }

  it("opens the share sheet with the file where the browser can", async () => {
    vi.restoreAllMocks();
    const spy = stubShare(true, async () => undefined);
    const { clicks } = stubDownload();
    const outcome = await share.deliverShareImage(
      new Blob(["png"]),
      card as ShareCard,
    );
    expect(outcome).toBe("shared");
    const data = spy.mock.calls[0]?.[0] as ShareData;
    expect(data.files?.[0]?.name).toBe("starvector-2026-12-01.png");
    expect(data.files?.[0]?.type).toBe("image/png");
    expect(clicks).toEqual([]);
  });

  it("saves nothing when the player closes the share sheet", async () => {
    vi.restoreAllMocks();
    stubShare(true, async () => {
      throw new DOMException("closed", "AbortError");
    });
    const { clicks } = stubDownload();
    expect(
      await share.deliverShareImage(new Blob(["png"]), card as ShareCard),
    ).toBe("cancelled");
    expect(clicks).toEqual([]);
  });

  it("saves the file where the browser cannot share one", async () => {
    vi.restoreAllMocks();
    const { clicks } = stubDownload();
    expect(
      await share.deliverShareImage(new Blob(["png"]), card as ShareCard),
    ).toBe("saved");
    expect(clicks).toEqual(["starvector-2026-12-01.png"]);
    // A browser with a share function that refuses files saves too.
    stubShare(false, async () => undefined);
    expect(
      await share.deliverShareImage(new Blob(["png"]), card as ShareCard),
    ).toBe("saved");
    // A share sheet that fails for a different cause saves the file.
    stubShare(true, async () => {
      throw new Error("not allowed");
    });
    expect(
      await share.deliverShareImage(new Blob(["png"]), card as ShareCard),
    ).toBe("saved");
    expect(clicks).toHaveLength(3);
  });
});
