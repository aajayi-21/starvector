import { expect, test } from "@playwright/test";

import { blockExternalHosts, SERVER, signIn, TOKENS } from "./helpers";

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

  await expect(page.getByText("The day's board")).toBeVisible();
  const wire = await (
    await page.request.get(`${SERVER}/api/leaderboard`)
  ).json();
  const board = page.locator(".card").filter({ hasText: "The day's board" });
  await expect(board.locator("tbody tr")).toHaveCount(wire.rows.length);
  await expect(board.getByText("you")).toBeVisible();

  // One revealed day means nobody is near the 30-trial floor, so
  // the skill board gates itself with no operator step. That is
  // the correct state here and the populated board is proved by
  // the component and unit tests.
  const skill = await (
    await page.request.get(`${SERVER}/api/leaderboard/skill`)
  ).json();
  expect(skill.active).toBe(false);
  await expect(
    page.getByText(/opens when a player has 30 trials/),
  ).toBeVisible();
  await expect(page.getByText(/of 30 eligible players/)).toBeVisible();
});

test("an invite link signs the browser in", async ({ browser }) => {
  // The regression gate for the three routing layers /join has to
  // cross. A fresh context with no planted cookie: the redirect
  // and the cookie both have to come from the server.
  //
  // The proxy entry and the service-worker denylist are covered
  // here. The production Caddy block is not and cannot be — after
  // a deploy, `curl -sI https://<host>/join/bogus` must answer the
  // server's JSON 401 and not text/html.
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`/join/${TOKENS.bru}`);

  // It lands on the app, not on the invite gate.
  expect(new URL(page.url()).pathname).toBe("/");
  await expect(page.getByText("Starvector")).toBeVisible();
  await expect(page.getByText(/not signed in/)).toBeHidden();

  // The cookie the server set is the one riding: this browser
  // reads bru's identity and not the configured player's.
  const cookies = await context.cookies();
  expect(cookies.find((one) => one.name === "sv_session")?.value).toBe(
    TOKENS.bru,
  );
  const me = await (await page.request.get(`${SERVER}/api/me`)).json();
  expect(me.player).toBe("bru");
  expect(me.display_name).toBe("Bru Lin");
  await context.close();
});

test("a browser with no invite meets the gate", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/");
  await expect(page.getByText(/not signed in/)).toBeVisible();
  await expect(page.getByText(/invite link/)).toBeVisible();
  // The gate replaces the app rather than sitting beside it.
  await expect(page.getByRole("link", { name: "Today" })).toBeHidden();
  await context.close();
});

test("a refused invite says nothing about who is stored", async ({
  browser,
}) => {
  // The enumeration oracle, walked through the real proxy. An
  // unknown name, a wrong secret, and a token that does not parse
  // must be one answer.
  const context = await browser.newContext();
  const answers = [];
  for (const token of [
    `bru.${"9".repeat(43)}`,
    `zzzz.${"9".repeat(43)}`,
    "not-a-token",
  ]) {
    const answer = await context.request.get(`/join/${token}`, {
      maxRedirects: 0,
    });
    answers.push([answer.status(), await answer.text()]);
  }
  expect(new Set(answers.map((one) => JSON.stringify(one))).size).toBe(1);
  expect(answers[0]?.[0]).toBe(401);
  await context.close();
});
