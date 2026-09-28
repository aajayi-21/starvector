import { expect, test } from "@playwright/test";

import { blockExternalHosts, signIn } from "./helpers";

// A 1x1 PNG — enough for createImageBitmap and the magic-byte
// check, and the downscale leaves it as it is.
const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8" +
  "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

// Spec A1 §3: the account page — reached from the avatar, the
// description saves, the picture uploads and removes, and the
// avatar follows the stored state.
test("the account page edits the description and the picture", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/");
  await page.getByLabel("Your account").click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(
    page.getByRole("heading", { name: "Your account" }),
  ).toBeVisible();

  // The description round-trips through PUT /api/account.
  const editor = page.getByRole("textbox", { name: "About you" });
  await editor.fill("I sketch coastlines.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("Saved")).toBeVisible();
  await page.reload();
  await expect(page.getByRole("textbox", { name: "About you" })).toHaveValue(
    "I sketch coastlines.",
  );

  // The picture: upload, then the top-bar avatar shows it.
  await page.getByLabel("Choose a profile picture").setInputFiles({
    name: "avatar.png",
    mimeType: "image/png",
    buffer: Buffer.from(PNG_BASE64, "base64"),
  });
  await expect(page.getByLabel("Your account").locator("img")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove picture" }),
  ).toBeVisible();

  // The remove control puts the initials back.
  await page.getByRole("button", { name: "Remove picture" }).click();
  await expect(
    page.getByRole("button", { name: "Remove picture" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Your account").locator("img")).toHaveCount(0);
});

// Spec BR1 §4: a device code signs a second browser in — the path a
// phone's home-screen app takes — and that device signs itself out.
test("a device code signs a second browser in", async ({ page, browser }) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/account");
  const add = page.getByRole("button", { name: "Add a device" });
  await expect(add).toBeEnabled();
  await add.click();
  const shown = page.getByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  await expect(shown).toBeVisible();
  const code = (await shown.textContent()) ?? "";

  const phone = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) " +
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 " +
      "Mobile/15E148 Safari/604.1",
  });
  const second = await phone.newPage();
  await second.goto("/");
  await second
    .getByLabel("Signed in on another device?")
    .fill(code.toLowerCase());
  await second.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(second.getByText(/, Ade$/)).toBeVisible();

  // The first browser sees the new device arrive and names it.
  await expect(page.getByText("Safari on iPhone is signed in.")).toBeVisible({
    timeout: 10_000,
  });

  // The code works one time.
  const third = await browser.newContext();
  const again = await third.request.post("/api/device-code/redeem", {
    data: { code },
  });
  expect(again.status()).toBe(400);
  await third.close();

  // The phone signs itself out and lands on the landing page.
  await second.goto("/account");
  await second.getByRole("button", { name: "Sign out of this device" }).click();
  await expect(second.getByText("A new hidden photo every day.")).toBeVisible();
  await phone.close();
});
