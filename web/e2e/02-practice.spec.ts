import { expect, test } from "@playwright/test";

import { blockExternalHosts, drawStroke } from "./helpers";

const PRACTICE_DAY = "2026-08-10";

test("a practice cycle scores against the revealed day", async ({ page }) => {
  await blockExternalHosts(page);
  await page.goto("/practice");
  await page.getByLabel("practice day").selectOption(PRACTICE_DAY);
  // The intake gate wants two or more strokes in a drawing.
  await drawStroke(page, [0.3, 0.6], [0.7, 0.4]);
  await drawStroke(page, [0.4, 0.3], [0.6, 0.7]);

  const imageLoaded = page.waitForResponse(
    (response) => response.url().includes("/image/") && response.ok(),
  );
  await page.getByRole("button", { name: "Score now" }).click();
  await expect(page.getByText(/beat \d+ of \d+ decoys/)).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText("1 scored this session")).toBeVisible();
  await imageLoaded;
});
