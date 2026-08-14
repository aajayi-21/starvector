import { expect, test } from "@playwright/test";

import { blockExternalHosts } from "./helpers";

const SERVER = "http://127.0.0.1:8199";
const LIVE_SECRET = "d".repeat(64);

test("close and reveal over HTTP, then the report renders", async ({
  page,
  request,
}) => {
  // The operator side, driven over HTTP against the fixture server.
  const closed = await request.post(`${SERVER}/api/day/close`, {
    timeout: 120_000,
  });
  expect(closed.ok()).toBeTruthy();
  const revealed = await request.post(`${SERVER}/api/day/reveal`, {
    timeout: 60_000,
  });
  expect(revealed.ok()).toBeTruthy();

  await blockExternalHosts(page);
  await page.goto("/reveal");
  await expect(page.getByText("Trial score")).toBeVisible();
  // The hero p is a 4-decimal number derived from the trial row —
  // scoped to the score card (the leaderboard holds more of them).
  await expect(
    page
      .locator(".card")
      .filter({ hasText: "Trial score" })
      .getByText(/^[01]\.\d{4}$/),
  ).toBeVisible();
  await expect(page.getByText(/You beat/)).toBeVisible();
  await expect(page.getByText(LIVE_SECRET)).toBeVisible();
  await expect(
    page.getByText("printf '%s:%s' TARGET SECRET | sha256sum"),
  ).toBeVisible();
  await expect(page.getByText("What matched")).toBeVisible();
  // The leaderboard card is mock-served for this day.
  await expect(page.getByText("Today's leaderboard")).toBeVisible();
});
