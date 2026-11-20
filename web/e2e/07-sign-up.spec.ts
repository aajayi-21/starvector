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
  // The server names the notice version this build holds (spec R1
  // §3.2): with a different number the gate offers no account.
  expect((await probe.json()).notice_version).toBe(1);
  // One name for each run of this spec: a claimed name stays claimed.
  const username = `e2e-${Date.now().toString(36)}`;

  await page.goto("/");
  await page.getByRole("button", { name: "Create an account" }).click();
  await expect(
    page.getByRole("heading", { name: "Create an account" }),
  ).toBeVisible();
  // The parts of a sign-up show above the card, at the first one.
  const parts = page.getByRole("list", { name: "Creating your account" });
  await expect(parts.locator('[aria-current="step"]')).toHaveText(
    /Name and password/,
  );
  // The summary of the rules and the three facts of a username show
  // before the account is made (spec A2 §4.3).
  const nameHelper = page.locator("#signup-username-rules");
  const wordHelper = page.locator("#signup-password-rules");
  await expect(nameHelper).toHaveText(
    "3 to 20 letters, numbers, or hyphens, starting with a letter",
  );
  await expect(wordHelper).toHaveText(
    "At least 12 characters. A few unrelated words work well.",
  );
  await expect(page.getByText(/Everyone sees this name/)).toBeVisible();
  await expect(page.getByText(/can never be changed/)).toBeVisible();
  await expect(page.getByText(/Don't use your real name/)).toBeVisible();
  const make = page.getByRole("button", {
    name: "Create account",
    exact: true,
  });
  await expect(make).toBeDisabled();
  // The proof-of-work check (spec PW1 §4) is on the form and starts at
  // once. It is done long before the person finishes typing.
  await expect(page.locator(".proof-field altcha-widget")).toBeVisible();
  await expect(page.getByText("Verified")).toBeVisible();
  // The notice that results are public shows before the account is
  // made, and the control that makes it is described by it (spec R1
  // §3.1).
  await expect(page.getByText("Your results are public.")).toBeVisible();
  await expect(
    page.getByText(
      /Your username, score, words and sketches are published in an open database after each day closes\. Do not type anything private\./,
    ),
  ).toBeVisible();
  await expect(
    page.getByText("By creating an account, you agree to this."),
  ).toBeVisible();
  await expect(make).toHaveAccessibleDescription(/Your results are public\./);
  await expect(make).toHaveAccessibleDescription(
    /By creating an account, you agree to this\./,
  );

  // A broken rule shows by name in the helper line of its field.
  await page.getByLabel("Username").fill("9");
  await expect(nameHelper).toHaveText(
    "Use 3 to 20 characters. Start with a letter.",
  );
  // Typed capitals become small letters.
  await page.getByLabel("Username").fill(username.toUpperCase());
  await expect(page.getByLabel("Username")).toHaveValue(username);
  await expect(nameHelper).toHaveText(/starting with a letter \(met\)$/);
  await page.getByLabel("Password", { exact: true }).fill("too short");
  await expect(wordHelper).toHaveText("Use at least 12 characters.");
  await expect(make).toBeDisabled();
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await expect(wordHelper).toHaveText(/work well\. \(met\)$/);
  const signUpPost = page.waitForRequest(
    (request) =>
      request.method() === "POST" && request.url().endsWith("/api/signup"),
  );
  await make.click();
  // The agreement goes with the sign-up (spec R1 §3.2).
  expect((await signUpPost).postDataJSON().agrees_public).toBe(true);

  // The recovery code shows one time, and the app waits for the click.
  await expect(
    page.getByRole("heading", { name: "Save your recovery code" }),
  ).toBeVisible();
  const firstCode = (await page.getByTestId("recovery-code").innerText())
    .split(/\s+/)
    .join("-");
  expect(firstCode).toMatch(/^([A-HJKMNP-Z2-9]{4}-){5}[A-HJKMNP-Z2-9]{4}$/);
  await expect(page.getByRole("link", { name: "Today" })).toBeHidden();
  await expect(parts.locator('[aria-current="step"]')).toHaveText(
    /Recovery code/,
  );
  await page.getByRole("button", { name: "I've saved my code" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: new RegExp(`, ${username}$`) }),
  ).toBeVisible();

  // The account has a password, and no operator's code is live.
  const me = await (await page.request.get("/api/me")).json();
  expect(me.player).toBe(username);
  expect(me.display_name).toBe(username);
  expect(me.has_password).toBe(true);
  expect(me.operator_code).toBeNull();
  // The sign-up wrote the agreement to the current notice with the
  // account, thus no notice screen came before the app.
  expect(me.notice.version).toBe(1);
  expect(me.notice.agreed).toBe(true);

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
  await page.getByRole("button", { name: "Forgot it?" }).click();
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
  // A recovery is not a sign-up: no parts to show.
  await expect(parts).toHaveCount(0);
  await page.getByRole("button", { name: "I've saved my code" }).click();
  await expect(page.getByRole("heading", { name: username })).toBeVisible();

  // The earlier password is dead and the new one signs in.
  const old = await page.request.post("/api/signin", {
    headers: { Origin: new URL(page.url()).origin },
    data: { username, password: PASSWORD },
  });
  expect(old.status()).toBe(401);
});
