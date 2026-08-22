import { expect, test } from "@playwright/test";

import { blockExternalHosts, signIn } from "./helpers";

// A 1x1 PNG — enough for createImageBitmap and the magic-byte
// check, and the downscale leaves it as it is.
const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8" +
  "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";

// Spec A1 §3: the account page — reached from the nav avatar, the
// description saves, the picture uploads and removes, and the nav
// circle follows the stored state.
test("the account page edits the description and the picture", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/");
  await page.getByLabel("your account").click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByText("Your account")).toBeVisible();

  // The description round-trips through PUT /api/account.
  const editor = page.getByLabel("account description");
  await editor.fill("I sketch coastlines.");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("saved")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("account description")).toHaveValue(
    "I sketch coastlines.",
  );

  // The picture: upload, then the nav circle shows it.
  await page.getByLabel("pick a profile picture").setInputFiles({
    name: "avatar.png",
    mimeType: "image/png",
    buffer: Buffer.from(PNG_BASE64, "base64"),
  });
  await expect(page.getByLabel("your account").locator("img")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Remove picture" }),
  ).toBeVisible();

  // The remove control puts the initials back.
  await page.getByRole("button", { name: "Remove picture" }).click();
  await expect(
    page.getByRole("button", { name: "Remove picture" }),
  ).toHaveCount(0);
  await expect(page.getByLabel("your account").locator("img")).toHaveCount(0);
});
