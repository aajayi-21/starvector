import { expect, test } from "@playwright/test";

import { blockExternalHosts, canvasPoint, drawStroke, signIn } from "./helpers";

const PRACTICE_DAY = "2026-08-10";
const RESULT = /matched this photo better than \d+ of the other \d+ photos/;

test("a practice check scores against the revealed day", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/practice");
  await page.getByLabel("Photo from").selectOption(PRACTICE_DAY);
  // The intake gate wants two or more strokes in a drawing.
  await drawStroke(page, [0.3, 0.6], [0.7, 0.4]);
  await drawStroke(page, [0.4, 0.3], [0.6, 0.7]);

  const imageLoaded = page.waitForResponse(
    (response) => response.url().includes("/image/") && response.ok(),
  );
  await page.getByRole("button", { name: "Check my practice" }).click();
  await expect(page.getByText(RESULT)).toBeVisible({ timeout: 60_000 });
  await expect(
    page.getByText(/Practice isn't saved and doesn't count/),
  ).toBeVisible();
  await imageLoaded;

  // Back to editing keeps the sketch, and a second check runs.
  await page.getByRole("button", { name: "Edit and check again" }).click();
  await expect(
    page.getByRole("button", { name: "Check my practice" }),
  ).toBeEnabled();
});

// Spec A1 §6: words alone activate the description channel, so a
// check with no strokes scores, and the report names the word.
test("typed words score without strokes", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/practice");
  await page.getByLabel("Photo from").selectOption(PRACTICE_DAY);
  const check = page.getByRole("button", { name: "Check my practice" });
  await expect(check).toBeDisabled();
  const input = page.getByLabel("Add a word");
  await input.fill("tall vertical structure");
  await input.press("Enter");
  await expect(check).toBeEnabled();
  await check.click();
  await expect(page.getByText(RESULT)).toBeVisible({ timeout: 60_000 });
  const report = page.locator("section").filter({ hasText: "What connected" });
  await expect(report.getByText("“tall vertical structure”")).toBeVisible();
});

test("labeled strokes ride the practice record", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/practice");
  await page.getByLabel("Photo from").selectOption(PRACTICE_DAY);
  await drawStroke(page, [0.3, 0.6], [0.7, 0.4]);
  await drawStroke(page, [0.4, 0.3], [0.6, 0.7]);
  await page.getByText("Label parts of your sketch").click();
  await page.getByRole("button", { name: "Pick strokes" }).click();
  // The first stroke passes through the canvas centre.
  const [x, y] = await canvasPoint(page, [0.5, 0.5]);
  await page.mouse.click(x, y);
  await page.getByLabel("Name the picked strokes").fill("tower");
  await page.getByRole("button", { name: "Label", exact: true }).click();
  await expect(page.getByText("tower", { exact: true })).toBeVisible();
  const sent = page.waitForRequest((request) =>
    request.url().includes("/api/practice/score"),
  );
  await page.getByRole("button", { name: "Check my practice" }).click();
  const request = await sent;
  const body = request.postDataJSON() as {
    record: { groups: Array<{ id: string; label: string }> };
  };
  expect(body.record.groups).toEqual([{ id: "g1", label: "tower" }]);
  await expect(page.getByText(RESULT)).toBeVisible({ timeout: 60_000 });
});
