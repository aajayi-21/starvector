import { expect, test } from "@playwright/test";

import { blockExternalHosts } from "./helpers";

// Spec A1 §4: the open door. The fixture server runs --dev, thus
// the gate grows the door card, and a typed name becomes a
// session. The off-world byte equality is a Python test — this
// spec drives the on-world flow a person walks.
test("the door turns a typed name into a session", async ({ page }) => {
  await blockExternalHosts(page);
  await page.goto("/");

  // No cookie: the gate renders, with the door card on a dev box.
  await expect(page.getByText("This browser is not signed in.")).toBeVisible();
  await expect(page.getByText("Dev door")).toBeVisible();

  await page.getByLabel("player name").fill("walkin");
  await page.getByLabel("display name").fill("Walk In");
  await page.getByRole("button", { name: "Create or sign in" }).click();

  // The cookie landed and the shell renders signed in.
  await expect(page.getByText("Starvector")).toBeVisible();
  await page.getByLabel("your account").click();
  await expect(page.getByText("Walk In")).toBeVisible();
  await expect(page.getByText("walkin", { exact: true })).toBeVisible();
});
