import { expect, test } from "@playwright/test";

import { blockExternalHosts, canvasPoint, drawStroke } from "./helpers";

test("the daily flow: draw, group, send, lock", async ({ page }) => {
  await blockExternalHosts(page);
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().includes("/api/submission")
    ) {
      posts += 1;
    }
  });

  await page.goto("/");
  await expect(page.locator(".target-code-cell")).toHaveCount(6);

  // Two strokes: a vertical mast and a second line beside it.
  await drawStroke(page, [0.2, 0.7], [0.25, 0.2]);
  await drawStroke(page, [0.35, 0.7], [0.33, 0.25]);
  await expect(page.getByText("2 strokes", { exact: true })).toBeVisible();

  await page
    .getByPlaceholder("one impression — Enter commits")
    .fill("tall vertical structure");
  await page.keyboard.press("Enter");

  // Explicit select mode: pick the first stroke at its midpoint.
  await page.getByRole("button", { name: "Select strokes" }).click();
  const [x, y] = await canvasPoint(page, [0.225, 0.45]);
  await page.mouse.click(x, y);
  await expect(page.getByText(/1 selected/)).toBeVisible();
  await page.getByPlaceholder("what is it? e.g. tower").fill("tower");
  await page.getByRole("button", { name: "Group", exact: true }).click();
  await expect(page.getByText(/g1 ·/)).toBeVisible();

  await page.getByRole("button", { name: "Send today's trial" }).click();
  await expect(
    page.getByText("Sent. The reveal opens after the day closes."),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/^[0-9a-f]{32}$/)).toBeVisible();

  // Server truth survives a reload.
  await page.reload();
  await expect(
    page.getByText("Sent. The reveal opens after the day closes."),
  ).toBeVisible();
  expect(posts).toBe(1);
});
