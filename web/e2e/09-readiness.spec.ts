import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { blockExternalHosts, SESSIONS, signIn } from "./helpers";

// Spec PL1: the stale tab against the real server, the poll that moves
// a screen with no reload, and the response policy of the Caddyfile
// against the built app.

const here = path.dirname(fileURLToPath(import.meta.url));

test("a stale tab gets the server's 409, spends nothing, and keeps the sketch", async ({
  page,
}) => {
  await signIn(page, SESSIONS.bru);
  await blockExternalHosts(page);
  // This tab was loaded on an earlier day: its view names a label that
  // is not the latest one. The rest of the path is real.
  let stale = true;
  await page.route("**/api/day", async (route) => {
    const answer = await route.fetch();
    const body = await answer.json();
    await route.fulfill({
      response: answer,
      json: stale ? { ...body, day: "2020-01-01", submitted: false } : body,
    });
  });
  const answers: number[] = [];
  page.on("response", (response) => {
    if (
      response.request().method() === "POST" &&
      response.url().includes("/api/submission")
    ) {
      answers.push(response.status());
    }
  });
  await page.goto("/today");
  await page.getByLabel("Add a word").fill("left from yesterday");
  await page.getByLabel("Add a word").press("Enter");
  await page.getByRole("button", { name: "Review and send" }).click();
  stale = false;
  await page.getByRole("button", { name: "Send today's session" }).click();

  await expect.poll(() => answers).toEqual([409]);
  // Nothing landed on the earlier label, and the word survives on the
  // device under the day it was typed for. This player's fixture send
  // is on the latest day, so the screen then reads "sent".
  const stored = await page.request.get(
    "http://127.0.0.1:8199/api/submission?day=2020-01-01",
  );
  expect(stored.status()).toBe(404);
  await expect
    .poll(() =>
      page.evaluate(() => window.localStorage.getItem("sv:draft:2020-01-01")),
    )
    .toContain("left from yesterday");
});

test("the home screen moves by itself when the close finishes", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.clock.install();
  let status = "closing";
  let reads = 0;
  await page.route("**/api/day", async (route) => {
    reads += 1;
    const answer = await route.fetch();
    const body = await answer.json();
    await route.fulfill({
      response: answer,
      json: { ...body, status, submitted: true },
    });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Today's session has closed" }),
  ).toBeVisible();
  const before = reads;
  status = "open";
  await page.clock.fastForward(21_000);
  await expect.poll(() => reads).toBeGreaterThan(before);
  await expect(page.getByText("You're in for today")).toBeVisible();
});

test("the built app obeys the Caddyfile's content policy", async ({ page }) => {
  const caddyfile = readFileSync(
    path.resolve(here, "../../deploy/Caddyfile"),
    "utf-8",
  );
  const found = /Content-Security-Policy "([^"]+)"/.exec(caddyfile);
  if (found === null || found[1] === undefined) {
    throw new Error("no Content-Security-Policy in the Caddyfile");
  }
  const policy = found[1];
  await signIn(page);
  await blockExternalHosts(page);
  await page.route(
    (url) => url.port === "4173" && !url.pathname.startsWith("/api"),
    async (route) => {
      try {
        const answer = await route.fetch();
        await route.fulfill({
          response: answer,
          headers: { ...answer.headers(), "content-security-policy": policy },
        });
      } catch {
        // The spec moved to the next screen while this read was in
        // flight, and the browser dropped it. A read of a page that is
        // gone has no policy to check. The violations come from the
        // console, and this does not hide one.
      }
    },
  );
  const violations: string[] = [];
  page.on("console", (message) => {
    if (message.text().includes("Content Security Policy")) {
      violations.push(message.text());
    }
  });
  for (const screen of ["/", "/today", "/practice", "/history", "/how"]) {
    await page.goto(screen);
    await expect(page.locator("#root")).not.toBeEmpty();
  }
  await page.goto("/practice");
  await expect(page.getByTestId("sketch-canvas")).toBeVisible();
  expect(violations).toEqual([]);
});
