import { expect, test } from "@playwright/test";

import { blockExternalHosts, canvasPoint, drawStroke, signIn } from "./helpers";

const PRACTICE_DAY = "2026-08-10";
const RESULT = /matched this photo better than \d+ of the other \d+ photos/;

test("a practice check scores against the revealed day", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  // The path holds the day that practice replays.
  await page.goto(`/practice?day=${PRACTICE_DAY}`);
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
  // The path holds the day that practice replays.
  await page.goto(`/practice?day=${PRACTICE_DAY}`);
  const check = page.getByRole("button", { name: "Check my practice" });
  await expect(check).toBeDisabled();
  const input = page.getByLabel("Add a word");
  await input.fill("tall vertical structure");
  await input.press("Enter");
  await expect(check).toBeEnabled();
  await check.click();
  await expect(page.getByText(RESULT)).toBeVisible({ timeout: 60_000 });
  const report = page.locator("section").filter({ hasText: "What connected" });
  await expect(
    report.getByText("tall vertical structure", { exact: true }),
  ).toBeVisible();
});

test("labeled strokes ride the practice record", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  // The path holds the day that practice replays.
  await page.goto(`/practice?day=${PRACTICE_DAY}`);
  await drawStroke(page, [0.3, 0.6], [0.7, 0.4]);
  await drawStroke(page, [0.4, 0.3], [0.6, 0.7]);
  await page.getByRole("button", { name: "Label parts" }).click();
  await page.getByRole("button", { name: "Pick lines" }).click();
  // The first stroke passes through the canvas centre.
  const [x, y] = await canvasPoint(page, [0.5, 0.5]);
  await page.mouse.click(x, y);
  await page.getByLabel("Name the picked lines").fill("tower");
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

// The row of days (the Studio design): a step back from today is
// practice, the date opens a calendar, and Today comes back.
test("the days step from today to practice and back", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/today");
  await page.getByRole("button", { name: "The day before" }).click();
  await expect(page).toHaveURL(/\/practice\?day=\d{4}-\d{2}-\d{2}$/);
  await expect(
    page.getByRole("button", { name: "Check my practice" }),
  ).toBeVisible();
  const first = page.url();
  await page.getByRole("button", { name: /^Practice/ }).click();
  const calendar = page.getByRole("dialog", { name: "Pick a day" });
  await expect(calendar).toBeVisible();
  // Each day of the calendar that can be pressed is a day to play.
  await calendar.locator("button.day-calendar-day").first().click();
  await expect(calendar).toBeHidden();
  await expect(page).toHaveURL(/\/practice\?day=\d{4}-\d{2}-\d{2}$/);
  expect(typeof first).toBe("string");
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(page).toHaveURL(/\/today$/);
});
