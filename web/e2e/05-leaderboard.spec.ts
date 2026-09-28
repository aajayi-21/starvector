import { expect, test } from "@playwright/test";

import {
  blockExternalHosts,
  OPERATOR_HEADERS,
  SERVER,
  signIn,
  TOKENS,
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
  await expect(board.getByText("You", { exact: true })).toBeVisible();

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

  // It lands on the app, not on the landing page.
  expect(new URL(page.url()).pathname).toBe("/");
  await expect(page.getByText(/, Bru Lin$/)).toBeVisible();
  await expect(page.getByText("A new hidden photo every day.")).toBeHidden();

  // The cookie the server set is the one riding: a new session of
  // bru's, and never the invite itself (spec BR1 §4).
  const cookies = await context.cookies();
  const session = cookies.find((one) => one.name === "sv_session")?.value;
  expect(session?.startsWith("bru.")).toBe(true);
  expect(session).not.toBe(TOKENS.bru);
  const me = await (await page.request.get(`${SERVER}/api/me`)).json();
  expect(me.player).toBe("bru");
  expect(me.display_name).toBe("Bru Lin");
  await context.close();
});

test("an operator mints an invite that signs a new browser in", async ({
  browser,
  request,
}) => {
  // The console's mint, over the wire it uses. The gate is the
  // bearer and not the operator gate of ruling 7: the switch that
  // turns access control on must not itself be open in the world
  // where nothing holds credentials.
  const refused = await request.post(`${SERVER}/api/players`, {
    data: { player: "cyd", display_name: "Cyd Vega" },
  });
  expect(refused.status()).toBe(401);

  const minted = await request.post(`${SERVER}/api/players`, {
    headers: OPERATOR_HEADERS,
    data: { player: "cyd", display_name: "Cyd Vega" },
  });
  expect(minted.ok()).toBeTruthy();
  const invite = await minted.json();
  // A path and not an address: the server does not know its public
  // origin and must not trust the Host header for one.
  expect(invite.join_path).toBe(`/join/${invite.token}`);

  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(invite.join_path);
  expect(new URL(page.url()).pathname).toBe("/");
  const me = await (await page.request.get(`${SERVER}/api/me`)).json();
  expect(me.player).toBe("cyd");
  expect(me.display_name).toBe("Cyd Vega");

  // The name is taken now, and the refusal says so.
  const again = await request.post(`${SERVER}/api/players`, {
    headers: OPERATOR_HEADERS,
    data: { player: "cyd", display_name: "Cyd Vega" },
  });
  expect(again.status()).toBe(409);
  await context.close();
});

test("a browser with no session meets the landing page", async ({
  browser,
}) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("/history");
  await expect(page.getByText("A new hidden photo every day.")).toBeVisible();
  await expect(page.getByText(/open the invite link/)).toBeVisible();
  await expect(page.getByLabel("Signed in on another device?")).toBeVisible();
  // The landing replaces the app rather than sitting beside it.
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
