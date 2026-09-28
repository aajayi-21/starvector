import { expect, test } from "@playwright/test";

import { OPERATOR_TOKEN } from "./helpers";

// Spec BR1 §7: the operator console over the fixture server. This
// spec runs last — "Do what is due now" opens a day on the real
// calendar, and no earlier spec may meet that day.

test("the console reads players, devices, and the results database", async ({
  page,
}) => {
  await page.goto("/dev.html");
  const token = page.getByLabel("operator token");
  await token.fill(OPERATOR_TOKEN);
  await token.blur();
  await expect(page.getByLabel("stored day")).toBeVisible();

  await page.getByRole("tab", { name: "Players" }).click();
  await page.getByRole("button", { name: "bru", exact: true }).click();
  await expect(page.getByText(/^Devices signed in · \d+$/)).toBeVisible();
  await page.getByRole("button", { name: "Device code" }).click();
  await expect(page.getByTestId("account-device-code")).toHaveText(
    /^[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$/,
  );

  await page.getByRole("tab", { name: "Results database" }).click();
  await page.getByRole("button", { name: "Players and accounts" }).click();
  await page.getByRole("button", { name: "Run query" }).click();
  const results = page.locator(".dev-results");
  await expect(
    results.getByRole("cell", { name: "ade", exact: true }),
  ).toBeVisible();
  await expect(
    results.getByRole("cell", { name: "bru", exact: true }),
  ).toBeVisible();

  await page.getByLabel("SQL query").fill("DELETE FROM trials");
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(page.getByRole("alert")).toContainText("read-only");
});

test("the console does what is due and the day moves", async ({ page }) => {
  page.on("dialog", (dialog) => void dialog.accept());
  await page.goto("/dev.html");
  const token = page.getByLabel("operator token");
  await token.fill(OPERATOR_TOKEN);
  await token.blur();

  await page.getByRole("tab", { name: "Automatic days" }).click();
  await expect(page.getByText("Automatic days are on")).toBeVisible();
  // The fixture's days are in August and the server reads the real
  // clock, thus a step is always due here.
  await page.getByRole("button", { name: "Do what is due now" }).click();
  await expect(page.getByText("This run · moved")).toBeVisible();
  await expect(page.getByText("Nothing is due now.")).toBeVisible();

  await page.getByRole("tab", { name: "Days", exact: true }).click();
  await expect(page.getByText("status open")).toBeVisible();
});
