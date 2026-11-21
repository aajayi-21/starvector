import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { blockExternalHosts, canvasPoint, drawStroke, signIn } from "./helpers";

/**
 * The width and the height of a JPEG, from its start-of-frame segment.
 * The file starts with the JPEG marker, and each segment before the
 * frame gives its own length.
 */
function jpegSize(bytes: Buffer): { width: number; height: number } {
  expect(bytes.subarray(0, 3)).toEqual(Buffer.from([0xff, 0xd8, 0xff]));
  let at = 2;
  while (at + 9 < bytes.length) {
    const marker = bytes[at + 1] as number;
    const length = bytes.readUInt16BE(at + 2);
    // SOF0 to SOF3: the frame header holds the height, then the width.
    if (marker >= 0xc0 && marker <= 0xc3) {
      return {
        height: bytes.readUInt16BE(at + 5),
        width: bytes.readUInt16BE(at + 7),
      };
    }
    at += 2 + length;
  }
  throw new Error("the file has no JPEG frame");
}

test("the daily flow: draw, label, send, lock", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  let posts = 0;
  let starts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/submission")
    ) {
      posts += 1;
    }
    if (
      request.method() === "POST" &&
      request.url().endsWith("/api/day/start")
    ) {
      starts += 1;
    }
  });

  // Home points at today with one primary step.
  await page.goto("/");
  const start = page.getByRole("link", { name: "Start today's sketch" });
  await expect(start).toBeVisible();
  // The home screen shows the code and sends no start (spec R1 §4).
  expect(starts).toBe(0);
  const startPost = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/api/day/start"),
  );
  await start.click();
  await expect(page).toHaveURL(/\/today$/);
  // The code is plain type, read as one image with its six characters.
  await expect(page.getByRole("img", { name: /^Code( \S){6}$/ })).toBeVisible();
  // The drawing screen reports the start, with no body, and the
  // answer is the one constant body.
  const started = await startPost;
  expect(started.request().postData()).toBeNull();
  expect(started.status()).toBe(200);
  expect(await started.json()).toEqual({ ok: true });

  // The fixture config sets the close time — the day view carries
  // the computed timestamp while open (spec S2 B1, spec BR1 §3).
  const dayView = await (
    await page.request.get("http://127.0.0.1:8199/api/day")
  ).json();
  expect(dayView.closes_at).toBe(`${dayView.day}T22:00:00+00:00`);

  // Send, then see (spec SS1 §4): the second player of the fixture has
  // sent, and this player has not. The server refuses the sketches of
  // the day with its one constant body.
  const sendsUrl = `http://127.0.0.1:8199/api/sends?day=${dayView.day}`;
  const refused = await page.request.get(sendsUrl);
  expect(refused.status()).toBe(404);
  expect(await refused.text()).toBe('{"detail":"sends not shown"}');

  // Two strokes: a vertical mast and a second line beside it.
  await drawStroke(page, [0.2, 0.7], [0.25, 0.2]);
  await drawStroke(page, [0.35, 0.7], [0.33, 0.25]);
  await expect(page.getByText("0 words, 2 lines")).toBeVisible();

  const word = page.getByLabel("Add a word");
  await word.fill("tall vertical structure");
  await word.press("Enter");
  await expect(page.getByText("1 word, 2 lines")).toBeVisible();

  // Label the first stroke as a part of the sketch.
  await page.getByText("Label parts of your sketch").click();
  await page.getByRole("button", { name: "Pick lines" }).click();
  const [x, y] = await canvasPoint(page, [0.225, 0.45]);
  await page.mouse.click(x, y);
  await expect(page.getByText(/1 line picked/)).toBeVisible();
  await page.getByLabel("Name the picked lines").fill("tower");
  await page.getByRole("button", { name: "Label", exact: true }).click();
  await expect(page.getByText(/1 labeled part/)).toBeVisible();

  // The review step lists the send, and a typed word that was not
  // added comes with it (spec PL1 §8).
  await word.fill("cold and bright");
  await page.getByRole("button", { name: "Review and send" }).click();
  await expect(page.getByText(/Include “cold and bright”/)).toBeVisible();
  await expect(posts).toBe(0);
  await page.getByRole("button", { name: "Send my sketch" }).click();
  await expect(page.getByText("Sent. You're in for today")).toBeVisible({
    timeout: 30_000,
  });

  // The player's own sketch saves as a JPEG before the reveal (spec SS1
  // §6). Chromium on this box has no share sheet for files, so the
  // control saves the file, and the spec reads the saved bytes.
  const shareSketch = page.getByRole("button", {
    name: "Share your sketch as an image",
  });
  await expect(shareSketch).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    shareSketch.click(),
  ]);
  expect(download.suggestedFilename()).toBe(
    `starvector-sketch-${dayView.day}.jpg`,
  );
  const image = await readFile((await download.path()) as string);
  expect(jpegSize(image)).toEqual({ width: 1080, height: 1350 });
  // A card with a sketch and its lines is not an empty canvas.
  expect(image.length).toBeGreaterThan(20_000);
  await expect(page.getByText("Image saved.")).toBeVisible();
  if (process.env.SV_SHARE_OUT) {
    await download.saveAs(`${process.env.SV_SHARE_OUT}/sketch.jpg`);
  }

  // Server truth survives a reload, and home agrees.
  await page.reload();
  await expect(page.getByText("Sent. You're in for today")).toBeVisible();
  await page.getByRole("link", { name: "Back to home" }).click();
  await expect(page.getByText("You're in for today")).toBeVisible();
  expect(posts).toBe(1);
  // One start for the open day: the sent view after the reload sends
  // no second one.
  expect(starts).toBe(1);

  // The send opens the sketches of the day to this player: the two
  // sends, the newest first, each as the sketch alone (spec SS1 §5).
  const sends = await (await page.request.get(sendsUrl)).json();
  expect(sends.total).toBe(2);
  expect(
    sends.entries.map((entry: { player: string }) => entry.player),
  ).toEqual(["ade", "bru"]);
  for (const entry of sends.entries) {
    expect(Object.keys(entry).sort()).toEqual([
      "avatar_hash",
      "named",
      "player",
      "state",
      "strokes",
    ]);
    expect(entry.state).toBe("sketch");
  }
  // No word, label, or note of a send is in the answer.
  const sendsText = JSON.stringify(sends);
  for (const text of ["tall vertical", "cold and bright", "tower", "group"]) {
    expect(sendsText).not.toContain(text);
  }
  // The count on the home screen is the control that opens them.
  await page.getByTestId("send-count").getByRole("link").click();
  await expect(page).toHaveURL(/\/sends\?day=/);
  await expect(
    page.getByRole("heading", { name: "Today's sketches" }),
  ).toBeVisible();
  const tiles = page.getByRole("list", { name: "Sketches" });
  await expect(tiles.getByRole("listitem")).toHaveCount(2);
  await expect(page.getByRole("img", { name: "Your sketch" })).toBeVisible();
  await expect(page.getByRole("img", { name: "Sketch by bru" })).toBeVisible();
});
