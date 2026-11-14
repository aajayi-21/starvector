import { expect, test } from "@playwright/test";

import { blockExternalHosts, canvasPoint, drawStroke, signIn } from "./helpers";

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
  const start = page.getByRole("link", { name: "Start today's session" });
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
  await expect(page.locator(".code-cell")).toHaveCount(6);
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

  // The review step lists the send, and a typed word that was not
  // added comes with it (spec PL1 §8).
  await word.fill("cold and bright");
  await page.getByRole("button", { name: "Review and send" }).click();
  await expect(page.getByText(/Include “cold and bright”/)).toBeVisible();
  await expect(posts).toBe(0);
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
  // One start for the open day: the sent view after the reload sends
  // no second one.
  expect(starts).toBe(1);
});
