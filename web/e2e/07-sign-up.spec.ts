import { expect, test } from "@playwright/test";

import { blockExternalHosts } from "./helpers";

// Spec A2 §3: a person makes an account with a username and a
// password, saves the recovery code, signs out, signs in, and gets
// back in with the recovery code.
//
// The flow needs a server that makes accounts: `signup` "open" in its
// config and a password digester. The server says which it is at
// GET /api/signup, and the spec stops with that reason when sign-up is
// closed - the gate screen then offers no account to make.

const PASSWORD = "four quiet amber lanterns";
const NEXT_PASSWORD = "five slow north harbors";

test("a new player signs up, signs in, and recovers", async ({ page }) => {
  await blockExternalHosts(page);
  const probe = await page.request.get("/api/signup");
  test.skip(
    probe.status() !== 200,
    "the fixture server has sign-up closed (GET /api/signup is not 200)",
  );
  // One name for each run of this spec: a claimed name stays claimed.
  const username = `e2e-${Date.now().toString(36)}`;

  await page.goto("/");
  await page.getByRole("button", { name: "Make an account" }).click();
  await expect(
    page.getByRole("heading", { name: "Make an account" }),
  ).toBeVisible();
  // The rules and the three facts of a username show before the
  // account is made (spec A2 §4.3).
  await expect(page.getByText("3 to 20 characters")).toBeVisible();
  await expect(page.getByText("12 to 128 characters")).toBeVisible();
  await expect(page.getByText(/can never be changed/)).toBeVisible();
  const make = page.getByRole("button", { name: "Make an account" });
  await expect(make).toBeDisabled();

  // Typed capitals become small letters.
  await page.getByLabel("Username").fill(username.toUpperCase());
  await expect(page.getByLabel("Username")).toHaveValue(username);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await make.click();

  // The recovery code shows one time, and the app waits for the click.
  await expect(
    page.getByRole("heading", { name: "Save your recovery code" }),
  ).toBeVisible();
  const firstCode = (await page.getByTestId("recovery-code").innerText())
    .split(/\s+/)
    .join("-");
  expect(firstCode).toMatch(/^([A-HJKMNP-Z2-9]{4}-){5}[A-HJKMNP-Z2-9]{4}$/);
  await expect(page.getByRole("link", { name: "Today" })).toBeHidden();
  await page.getByRole("button", { name: "I have my code" }).click();
  await expect(page.getByText(new RegExp(`, ${username}$`))).toBeVisible();

  // The account has a password, and no operator's code is live.
  const me = await (await page.request.get("/api/me")).json();
  expect(me.player).toBe(username);
  expect(me.display_name).toBe(username);
  expect(me.has_password).toBe(true);
  expect(me.operator_code).toBeNull();

  // Sign out, then sign in with the pair.
  await page.goto("/account");
  await page.getByRole("button", { name: "Sign out of this device" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill("not the password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "The username or the password is wrong.",
  );
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  // The sign-in was on the account address, and the app stays there.
  await expect(page.getByRole("heading", { name: username })).toBeVisible();

  // Sign out again, and get back in with the recovery code. Small
  // letters and spaces: capitals and hyphens do not count.
  await page.goto("/account");
  await page.getByRole("button", { name: "Sign out of this device" }).click();
  await page.getByRole("button", { name: "I do not have my password" }).click();
  await page.getByLabel("Username").fill(username);
  await page
    .getByRole("textbox", { name: "Recovery code" })
    .fill(firstCode.toLowerCase().replaceAll("-", " "));
  await page.getByLabel("New password", { exact: true }).fill(NEXT_PASSWORD);
  await page.getByRole("button", { name: "Set a new password" }).click();
  await expect(
    page.getByRole("heading", { name: "Save your recovery code" }),
  ).toBeVisible();
  const secondCode = (await page.getByTestId("recovery-code").innerText())
    .split(/\s+/)
    .join("-");
  expect(secondCode).not.toBe(firstCode);
  await page.getByRole("button", { name: "I have my code" }).click();
  await expect(page.getByRole("heading", { name: username })).toBeVisible();

  // The earlier password is dead and the new one signs in.
  const old = await page.request.post("/api/signin", {
    headers: { Origin: new URL(page.url()).origin },
    data: { username, password: PASSWORD },
  });
  expect(old.status()).toBe(401);
});
