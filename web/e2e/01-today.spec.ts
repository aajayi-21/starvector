import { expect, test } from "@playwright/test";

import { blockExternalHosts, canvasPoint, drawStroke, signIn } from "./helpers";

test("the daily flow: draw, label, send, lock", async ({ page }) => {
  await signIn(page);
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

  // Home points at today with one primary step.
  await page.goto("/");
  await page.getByRole("link", { name: "Start today's session" }).click();
  await expect(page).toHaveURL(/\/today$/);
  await expect(page.locator(".code-cell")).toHaveCount(6);

  // The fixture config sets the close time — the day view carries
  // the computed timestamp while open (spec S2 B1, spec BR1 §3).
  const dayView = await (
    await page.request.get("http://127.0.0.1:8199/api/day")
  ).json();
  expect(dayView.closes_at).toBe(`${dayView.day}T22:00:00+00:00`);

  // Two strokes: a vertical mast and a second line beside it.
  await drawStroke(page, [0.2, 0.7], [0.25, 0.2]);
  await drawStroke(page, [0.35, 0.7], [0.33, 0.25]);
  await expect(page.getByText("0 words · 2 strokes")).toBeVisible();

  const word = page.getByLabel("Add a word");
  await word.fill("tall vertical structure");
  await word.press("Enter");
  await expect(page.getByText("1 word · 2 strokes")).toBeVisible();

  // Label the first stroke as a part of the sketch.
  await page.getByText("Label parts of your sketch").click();
  await page.getByRole("button", { name: "Pick strokes" }).click();
  const [x, y] = await canvasPoint(page, [0.225, 0.45]);
  await page.mouse.click(x, y);
  await expect(page.getByText(/1 stroke picked/)).toBeVisible();
  await page.getByLabel("Name the picked strokes").fill("tower");
  await page.getByRole("button", { name: "Label", exact: true }).click();
  await expect(page.getByText(/1 labeled part/)).toBeVisible();

  await page.getByRole("button", { name: "Send today's session" }).click();
  await expect(page.getByText("Sent — you're in for today")).toBeVisible({
    timeout: 30_000,
  });

  // Server truth survives a reload, and home agrees.
  await page.reload();
  await expect(page.getByText("Sent — you're in for today")).toBeVisible();
  await page.getByRole("link", { name: "Back to home" }).click();
  await expect(page.getByText("You're in for today")).toBeVisible();
  expect(posts).toBe(1);
});
