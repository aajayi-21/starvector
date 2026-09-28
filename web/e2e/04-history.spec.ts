import { expect, test } from "@playwright/test";

import { blockExternalHosts, signIn } from "./helpers";

test("your results render the live numbers", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  const expected = await (
    await page.request.get("http://127.0.0.1:8199/api/history")
  ).json();
  expect(expected.days.length).toBeGreaterThan(0);
  const theta = expected.skill?.theta.toFixed(2);
  expect(theta).toBeDefined();

  await page.goto("/history");
  await expect(page.getByText("Skill number")).toBeVisible();
  await expect(page.getByText(theta as string, { exact: true })).toBeVisible();
  const table = page.locator("section").filter({ hasText: "Every day" });
  await expect(table.locator("tbody tr")).toHaveCount(expected.days.length);
  await expect(
    table.getByRole("link", { name: "Details" }).first(),
  ).toBeVisible();
});

test("keyboard focus lands on the top bar with a visible ring", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/history");
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toBeVisible();
  const outline = await focused.evaluate(
    (el) => getComputedStyle(el).outlineStyle,
  );
  expect(outline).not.toBe("none");
});
