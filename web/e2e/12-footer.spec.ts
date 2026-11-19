import { expect, test } from "@playwright/test";

import { blockExternalHosts, signIn } from "./helpers";

// Spec F1: the site footer and the two public pages, against the real
// server. A browser with no session gets a 401 for /api/me, and the
// two public paths open all the same.

test("the public pages open with no session, and the footer goes between them", async ({
  page,
}) => {
  await blockExternalHosts(page);
  await page.goto("/about");
  await expect(
    page.getByRole("heading", { name: "About Starvector" }),
  ).toBeVisible();
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "GitHub" })).toHaveAttribute(
    "href",
    "https://github.com/aajayi-21/starvector",
  );
  await footer.getByRole("link", { name: "Releases" }).click();
  await expect(page).toHaveURL(/\/releases$/);
  await expect(page.getByText("No releases to download yet.")).toBeVisible();
  // The way to the gate, and the gate has the footer too.
  await page.getByRole("link", { name: "Sign in" }).click();
  await expect(page.getByLabel("Username")).toBeVisible();
  await expect(page.getByRole("contentinfo")).toBeVisible();
});

test("each other path keeps the gate for a browser with no session", async ({
  page,
}) => {
  await blockExternalHosts(page);
  await page.goto("/history");
  await expect(page.getByLabel("Username")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
});

test("a signed-in player has the footer on the app screens and not on the drawing screen", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/history");
  const footer = page.getByRole("contentinfo");
  await expect(footer).toBeVisible();
  await footer.getByRole("link", { name: "About" }).click();
  await expect(
    page.getByRole("heading", { name: "About Starvector" }),
  ).toBeVisible();
  // Signed in, the public page keeps the app around it.
  await expect(
    page.getByRole("navigation", { name: "Main" }).first(),
  ).toBeVisible();
  await page.goto("/today");
  await expect(
    page.getByRole("navigation", { name: "Main" }).first(),
  ).toBeVisible();
  await expect(page.getByRole("contentinfo")).toHaveCount(0);
});
