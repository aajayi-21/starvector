import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

import { blockExternalHosts, signIn } from "./helpers";

// The share control makes a PNG of one result on the device. Chromium
// on this box has no share sheet for files, so the control saves the
// file, and the spec reads the saved bytes.

/** The width and the height of a PNG, from its IHDR chunk. */
function pngSize(bytes: Buffer): { width: number; height: number } {
  expect(bytes.subarray(0, 8)).toEqual(
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  );
  expect(bytes.subarray(12, 16).toString("latin1")).toBe("IHDR");
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

test("a past result saves as an image from the results list", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  const history = await (
    await page.request.get("http://127.0.0.1:8199/api/history")
  ).json();
  const row = history.days[0];
  expect(row).toBeDefined();

  await page.goto("/history");
  const table = page.locator("section").filter({ hasText: "Every day" });
  const button = table
    .getByRole("button", { name: /^Share the result of .* as an image$/ })
    .first();
  await expect(button).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    button.click(),
  ]);
  expect(download.suggestedFilename()).toBe(`starvector-${row.day}.png`);
  const bytes = await readFile((await download.path()) as string);
  expect(pngSize(bytes)).toEqual({ width: 1080, height: 1350 });
  // A card with text and a sketch is not an empty canvas.
  expect(bytes.length).toBeGreaterThan(20_000);
  await expect(table.getByText("Image saved.")).toBeVisible();
  if (process.env.SV_SHARE_OUT) {
    await download.saveAs(`${process.env.SV_SHARE_OUT}/from-list.png`);
  }
});

test("the results screen of a day has the share control too", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  const history = await (
    await page.request.get("http://127.0.0.1:8199/api/history")
  ).json();
  const day = history.days[0].day;
  await page.goto(`/reveal?day=${day}`);
  const button = page.getByRole("button", {
    name: /^Share the result of .* as an image$/,
  });
  await expect(button).toBeVisible();
  await expect(button).toContainText("Share");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    button.click(),
  ]);
  expect(download.suggestedFilename()).toBe(`starvector-${day}.png`);
  const bytes = await readFile((await download.path()) as string);
  expect(pngSize(bytes)).toEqual({ width: 1080, height: 1350 });
  // The image is made on the device: no request leaves for it.
  if (process.env.SV_SHARE_OUT) {
    await download.saveAs(`${process.env.SV_SHARE_OUT}/from-day.png`);
  }
});
