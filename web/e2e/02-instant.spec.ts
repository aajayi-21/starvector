import { expect, test } from "@playwright/test";

import { blockExternalHosts, drawStroke, signIn } from "./helpers";

// Spec IM1: the instant trial against the real server, with the fake
// beacon and the loop that gives each send its result.

const RESULT = /matched this photo better than \d+ of the other \d+ photos/;

test("an account plays an instant trial and sees the photo", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/instant");
  // The switch between the two modes of Play.
  const modes = page.getByRole("navigation", { name: "Play modes" });
  await expect(
    modes.getByRole("link", { name: "Instant trial" }),
  ).toHaveAttribute("aria-current", "page");
  await expect(page.getByText(/of 20 left today/)).toBeVisible();
  await page.getByRole("button", { name: "Get a code" }).click();

  const send = page.getByRole("button", { name: "Send", exact: true });
  await expect(send).toBeDisabled();
  // The intake gate wants two or more strokes in a drawing.
  await drawStroke(page, [0.3, 0.6], [0.7, 0.4]);
  await drawStroke(page, [0.4, 0.3], [0.6, 0.7]);
  const input = page.getByLabel("Add a word");
  await input.fill("tall vertical structure");
  await input.press("Enter");

  const imageLoaded = page.waitForResponse(
    (response) => response.url().includes("/image/") && response.ok(),
  );
  const sent = page.waitForResponse(
    (response) =>
      response.url().endsWith("/send") &&
      response.request().method() === "POST",
  );
  await send.click();
  // The receipt names a pulse that comes after the send.
  const receipt = await (await sent).json();
  expect(receipt.pulse_time).toBeGreaterThan(
    Date.parse(receipt.received_at) / 1000,
  );
  await expect(page.getByText(RESULT)).toBeVisible({ timeout: 60_000 });
  await imageLoaded;
  await expect(page.getByText("How this photo was picked")).toBeVisible();
  const report = page.locator("section").filter({ hasText: "What connected" });
  await expect(
    report.getByText("tall vertical structure", { exact: true }),
  ).toBeVisible();

  // The trial is in the record, and a second code is a new trial.
  await page.getByRole("button", { name: "Again" }).click();
  await expect(page.getByText(/Your record: 1 trial/)).toBeVisible();
  await expect(page.getByText(/^19 of 20 left today/)).toBeVisible();
});

test("a guest plays with no account, then makes one and keeps the trial", async ({
  page,
}) => {
  await blockExternalHosts(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Try an instant trial" }).click();
  // The notice comes before the guest is made (spec IM1 ruling 6).
  await expect(
    page.getByText("Your sketches and results are public."),
  ).toBeVisible();
  const agree = page.getByRole("button", { name: "I agree" });
  // The proof of work runs first, then the control opens.
  await expect(agree).toBeEnabled({ timeout: 30_000 });
  await agree.click();
  await expect(page.getByText("Playing as a guest")).toBeVisible();
  await expect(page.getByText(/of 5 left today/)).toBeVisible();

  // A guest gets the constant 401 on a daily path.
  expect((await page.request.get("/api/day")).status()).toBe(401);
  const guest = await (await page.request.get("/api/instant")).json();
  expect(guest.kind).toBe("guest");

  await page.getByRole("button", { name: "Get a code" }).click();
  await drawStroke(page, [0.3, 0.6], [0.7, 0.4]);
  await drawStroke(page, [0.4, 0.3], [0.6, 0.7]);
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText(RESULT)).toBeVisible({ timeout: 60_000 });

  // The daily challenge is a closed door for a guest.
  await page
    .getByRole("navigation", { name: "Play modes" })
    .getByRole("link", { name: "Daily challenge" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Daily challenge" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Make an account", exact: true })
    .click();

  // The sign-up claims the guest of this browser (spec IM1 §7.4).
  const username = `e2e-g${Date.now().toString(36)}`;
  await page.getByRole("button", { name: "Create an account" }).click();
  await page.getByLabel("Username").fill(username);
  await page
    .getByLabel("Password", { exact: true })
    .fill("four quiet amber lanterns");
  const make = page.getByRole("button", {
    name: "Create account",
    exact: true,
  });
  await expect(make).toBeEnabled({ timeout: 30_000 });
  await make.click();
  await page.getByRole("button", { name: "I've saved my code" }).click();
  // The browser was on the path of the daily challenge, thus the app
  // of the new account opens there, with its places in the top bar.
  await expect(page.getByRole("link", { name: "Your results" })).toBeVisible();
  await expect(page.getByText("Playing as a guest")).toBeHidden();
  const me = await (await page.request.get("/api/me")).json();
  expect(me.player).toBe(username);
  const account = await (await page.request.get("/api/instant")).json();
  expect(account.kind).toBe("account");
  expect(account.owner).toBe(username);
  expect(account.record.sent).toBe(1);
  expect(account.left_today).toBe(19);
});
