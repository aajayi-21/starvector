import { expect, test } from "@playwright/test";

import {
  blockExternalHosts,
  OPERATOR_HEADERS,
  SERVER,
  signIn,
} from "./helpers";

const LIVE_SECRET = "d".repeat(64);

test("close and reveal over HTTP, then the results render", async ({
  page,
  request,
}) => {
  // The operator side, driven over HTTP against the fixture
  // server. The standalone `request` fixture holds its own empty
  // cookie jar, thus these two carry the bearer explicitly.
  const closed = await request.post(`${SERVER}/api/day/close`, {
    timeout: 120_000,
    headers: OPERATOR_HEADERS,
  });
  expect(closed.ok()).toBeTruthy();
  const revealed = await request.post(`${SERVER}/api/day/reveal`, {
    timeout: 60_000,
    headers: OPERATOR_HEADERS,
  });
  expect(revealed.ok()).toBeTruthy();

  await signIn(page);
  await blockExternalHosts(page);
  // Home sends the revealed day to its results.
  await page.goto("/");
  await page
    .getByRole("link", { name: /^See (your result|the photo)$/ })
    .click();
  await expect(page).toHaveURL(/\/reveal$/);

  await expect(
    page.getByRole("heading", { name: /^You beat \d+% of the photos$/ }),
  ).toBeVisible();
  await expect(
    page.getByText(/matched the hidden photo better than/),
  ).toBeVisible();
  await expect(page.getByText("What connected")).toBeVisible();

  // The fairness check folds away and holds the command to run.
  await page.getByText("Check that this day was fair").click();
  await expect(page.getByText(LIVE_SECRET).first()).toBeVisible();
  await expect(page.getByText(/\| sha256sum$/)).toBeVisible();

  // The live board serves both players who sent (spec M1 B8): the
  // caller as "You", the other by display name.
  const wire = await (
    await page.request.get(`${SERVER}/api/leaderboard`)
  ).json();
  expect(wire.rows.length).toBe(2);
  const board = page
    .locator("section")
    .filter({ hasText: "Everyone this day" });
  await expect(board.locator("tbody tr")).toHaveCount(wire.rows.length);
  await expect(board.getByText("You", { exact: true })).toBeVisible();
  await expect(board.getByText("Bru Lin")).toBeVisible();

  // The sketch replays from the live stored submission.
  await expect(page.locator(".picture-frame canvas")).toHaveCount(1);
  await expect(page.getByText(/isn't stored on this device/)).toBeHidden();
});
