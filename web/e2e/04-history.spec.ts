import { expect, test } from "@playwright/test";

import { makeMockApi } from "../src/api/mock";
import { blockExternalHosts } from "./helpers";

test("history renders the pinned mock numbers", async ({ page }) => {
  await blockExternalHosts(page);
  const today = new Date().toISOString().slice(0, 10);
  const expected = await makeMockApi({ today }).getHistory();
  const theta = expected.skill?.theta.toFixed(3);
  expect(theta).toBeDefined();

  await page.goto("/history");
  await expect(page.getByText("Skill number")).toBeVisible();
  await expect(page.getByText(theta as string)).toBeVisible();
  await expect(page.locator(".card table tbody tr")).toHaveCount(
    expected.days.length,
  );
  await expect(
    page.getByRole("link", { name: "report" }).first(),
  ).toBeVisible();
});

test("keyboard focus lands on the nav with a visible ring", async ({
  page,
}) => {
  await blockExternalHosts(page);
  await page.goto("/history");
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toBeVisible();
  const outline = await focused.evaluate(
    (el) => getComputedStyle(el).outlineStyle,
  );
  expect(outline).not.toBe("none");
});
