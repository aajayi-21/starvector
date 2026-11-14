import { expect, test } from "@playwright/test";

import { blockExternalHosts, OPERATOR_TOKEN } from "./helpers";

// Spec A1 §4: the open door. The fixture server runs --dev, thus
// the landing page grows the name sign-in, and a typed name becomes
// a session. The off-world byte equality is a Python test — this
// spec drives the on-world flow a person walks.
test("the name sign-in turns a typed name into a session", async ({ page }) => {
  await blockExternalHosts(page);
  await page.goto("/");

  // No cookie: the landing page renders, with the name sign-in on
  // a test server.
  await expect(page.getByText("A new hidden photo every day.")).toBeVisible();
  await expect(page.getByText("Test server sign-in")).toBeVisible();

  // A name and no second label: the username is the one name of a
  // player (spec A2 ruling 3).
  await expect(page.getByLabel(/Display name/)).toHaveCount(0);
  await page.getByLabel("Player name").fill("walkin");

  // With no operator token the door stays shut (spec PL1 §5): the dev
  // unit shares the production store.
  await page.getByRole("button", { name: "Sign in by name" }).click();
  await expect(
    page.getByText("Name sign-in needs the operator token on this server."),
  ).toBeVisible();

  await page.getByLabel("Operator token").fill(OPERATOR_TOKEN);
  await page.getByRole("button", { name: "Sign in by name" }).click();

  // The cookie landed and the shell renders signed in.
  await expect(
    page.getByRole("heading", { level: 1, name: /, walkin$/ }),
  ).toBeVisible();
  await page.getByLabel("Your account").click();
  await expect(page.getByRole("heading", { name: "walkin" })).toBeVisible();
  // A door record has no password (spec A2 §10.2), thus the account
  // screen offers the first one.
  await expect(
    page.getByRole("heading", { name: "Set a password" }),
  ).toBeVisible();
});
