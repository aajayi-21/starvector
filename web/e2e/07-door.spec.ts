import { expect, test } from "@playwright/test";

import { blockExternalHosts } from "./helpers";

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

  await page.getByLabel("Player name").fill("walkin");
  await page.getByLabel(/Display name/).fill("Walk In");
  await page.getByRole("button", { name: "Sign in by name" }).click();

  // The cookie landed and the shell renders signed in.
  await expect(page.getByText(/, Walk In$/)).toBeVisible();
  await page.getByLabel("Your account").click();
  await expect(page.getByRole("heading", { name: "Walk In" })).toBeVisible();
  await expect(page.getByText("Player id: walkin")).toBeVisible();
});
