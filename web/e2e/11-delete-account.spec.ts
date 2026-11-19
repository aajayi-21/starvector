import { expect, test } from "@playwright/test";

import { blockExternalHosts } from "./helpers";

// Spec MD1 §4.3: a player deletes their own account from the account
// page with the username typed again and the password. The cookie
// goes, the app shows the landing page, and the name stays closed.

const PASSWORD = "four quiet amber lanterns";

test("a player deletes their own account", async ({ page }) => {
  await blockExternalHosts(page);
  const probe = await page.request.get("/api/signup");
  test.skip(
    probe.status() !== 200,
    "the fixture server has sign-up closed (GET /api/signup is not 200)",
  );
  // One name for each run: a deleted name stays claimed.
  const username = `del-${Date.now().toString(36)}`;
  await page.goto("/");
  const origin = new URL(page.url()).origin;
  const made = await page.request.post("/api/signup", {
    headers: { Origin: origin },
    data: { username, password: PASSWORD, agrees_public: true },
  });
  expect(made.status()).toBe(201);

  await page.goto("/account");
  // The section is closed at first: the `Delete account` row, the last
  // row of the page, opens it.
  const heading = page.getByRole("heading", { name: "Delete my account" });
  const row = page.getByRole("button", { name: "Delete account", exact: true });
  await expect(row).toHaveAttribute("aria-expanded", "false");
  await expect(heading).toHaveCount(0);
  await row.click();
  await expect(heading).toBeFocused();
  await expect(page.getByText("This can't be reversed.")).toBeVisible();

  // `Keep my account` closes the section and goes back to the row.
  await page.getByRole("button", { name: "Keep my account" }).click();
  await expect(heading).toHaveCount(0);
  await expect(row).toBeFocused();
  await row.click();

  const remove = page.getByRole("button", { name: "Delete my account" });
  await expect(remove).toBeDisabled();
  await page.getByLabel(`Type ${username} to confirm`).fill(username);
  // By id: the label row of the password field is a shared component.
  await page.locator("#delete-password").fill(PASSWORD);
  await expect(remove).toBeEnabled();
  await remove.click();
  await expect(
    page.getByText(
      /Your account is deleted\. Your earlier results show as anon-[0-9a-f]{16}\./,
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Done" }).click();
  await expect(
    page.getByRole("button", { name: "Create an account" }),
  ).toBeVisible();

  // The name is closed for each new sign-up, and the password signs
  // nobody in.
  const again = await page.request.post("/api/signup", {
    headers: { Origin: origin },
    data: { username, password: PASSWORD, agrees_public: true },
  });
  expect(again.status()).toBe(409);
  const signIn = await page.request.post("/api/signin", {
    headers: { Origin: origin },
    data: { username, password: PASSWORD },
  });
  expect(signIn.status()).toBe(401);
});
