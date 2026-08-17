import { expect, test } from "@playwright/test";

import {
  blockExternalHosts,
  OPERATOR_HEADERS,
  SERVER,
  signIn,
} from "./helpers";

const LIVE_SECRET = "d".repeat(64);

test("close and reveal over HTTP, then the report renders", async ({
  page,
  request,
}) => {
  // The operator side, driven over HTTP against the fixture
  // server. The standalone `request` fixture holds its own empty
  // cookie jar, thus these two carry the bearer explicitly - a
  // session planted on `page` would not reach them.
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
  // The live leaderboard serves both players who sent (spec M1
  // B8): the caller as "you", the other by display name. The row
  // count is read from the wire rather than written down, so a
  // fixture that grows does not need this edited.
  await expect(page.getByText("Today's leaderboard")).toBeVisible();
  const wire = await (
    await page.request.get(`${SERVER}/api/leaderboard`)
  ).json();
  expect(wire.rows.length).toBe(2);
  const board = page.locator(".card").filter({
    hasText: "Today's leaderboard",
  });
  await expect(board.locator("tbody tr")).toHaveCount(wire.rows.length);
  await expect(board.getByText("you")).toBeVisible();
  await expect(board.getByText("Bru Lin")).toBeVisible();
  // The sketch replays from the live stored submission.
  await expect(page.getByText("Your sketch")).toBeVisible();
  await expect(page.getByText(/No stored sketch/)).toBeHidden();
});
