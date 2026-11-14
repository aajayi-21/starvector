import { expect, test } from "@playwright/test";

import {
  blockExternalHosts,
  OPERATOR_HEADERS,
  SERVER,
  signIn,
} from "./helpers";

test("the leaderboard serves the day's board and gates the skill board", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/leaderboard");

  // The nav item leaves the reveal screen for a screen of its own
  // (spec M1 §9), and the reveal screen keeps its own card.
  await expect(page.getByRole("link", { name: "Leaderboard" })).toHaveAttribute(
    "aria-current",
    "page",
  );

  await expect(page.getByRole("heading", { name: "Latest day" })).toBeVisible();
  const wire = await (
    await page.request.get(`${SERVER}/api/leaderboard`)
  ).json();
  const board = page.locator("section").filter({ hasText: "Latest day" });
  await expect(board.locator("tbody tr")).toHaveCount(wire.rows.length);
  // A row with a streak mark adds a hidden "N-day streak" label to the
  // name (spec H1 §4), so the match starts at "You" and does not end there.
  await expect(board.getByText(/^You/)).toBeVisible();

  // One revealed day means nobody is near the 30-trial floor, so
  // the skill board gates itself with no operator step. That is
  // the correct state here and the populated board is proved by
  // the component and unit tests.
  const skill = await (
    await page.request.get(`${SERVER}/api/leaderboard/skill`)
  ).json();
  expect(skill.active).toBe(false);
  await expect(
    page.getByText(/starts once a player has sent 30 results/),
  ).toBeVisible();
  await expect(
    page.getByText(/After 30 players reach 30 results/),
  ).toBeVisible();
});

test("the invite paths are gone (spec A2 §10.1)", async ({
  browser,
  request,
}) => {
  // GET /join/{token} answers the constant 404, walked through the
  // preview proxy as a browser walks it. A token of the earlier
  // shape, a name with no record, and text that is no token get one
  // answer, thus the path says nothing about who is stored.
  const context = await browser.newContext();
  const answers = [];
  for (const token of [
    `bru.${"2".repeat(43)}`,
    `zzzz.${"9".repeat(43)}`,
    "not-a-token",
  ]) {
    const answer = await context.request.get(`/join/${token}`, {
      maxRedirects: 0,
    });
    answers.push([answer.status(), await answer.text()]);
  }
  expect(new Set(answers.map((one) => JSON.stringify(one))).size).toBe(1);
  expect(answers[0]?.[0]).toBe(404);
  // No cookie came with the answer.
  expect(await context.cookies()).toHaveLength(0);
  await context.close();

  // The POST that made a player is gone too, with the bearer and
  // with none: an operator makes no account.
  for (const headers of [{}, OPERATOR_HEADERS]) {
    const made = await request.post(`${SERVER}/api/players`, {
      headers,
      data: { player: "cyd", display_name: "Cyd Vega" },
    });
    expect(made.ok()).toBe(false);
  }
  const roster = await (
    await request.get(`${SERVER}/api/dev/players`, {
      headers: OPERATOR_HEADERS,
    })
  ).json();
  expect(
    roster.players.map((row: { player: string }) => row.player),
  ).not.toContain("cyd");
});

test("a browser with no session meets the gate screen", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/history");
  await expect(page.getByText("A new hidden photo every day.")).toBeVisible();
  // The gate of spec A2 §3: a username and a password to type, the
  // recovery control, and the device code. No invite to open.
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByLabel("Username")).toBeVisible();
  await expect(page.getByLabel("Password", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("button", { name: "I do not have my password" }),
  ).toBeVisible();
  await expect(page.getByLabel("Signed in on another device?")).toBeVisible();
  await expect(page.getByText(/invite/i)).toHaveCount(0);
  // The landing replaces the app rather than sitting beside it.
  await expect(page.getByRole("link", { name: "Today" })).toBeHidden();

  // A pair that does not sign in gets one answer, and the page says
  // the pair is wrong without saying which half.
  await page.getByLabel("Username").fill("bru");
  await page.getByLabel("Password", { exact: true }).fill("not the password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByRole("link", { name: "Today" })).toBeHidden();
  await context.close();
});
