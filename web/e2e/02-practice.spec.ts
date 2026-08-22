import { expect, test } from "@playwright/test";

import { blockExternalHosts, canvasPoint, drawStroke, signIn } from "./helpers";

const PRACTICE_DAY = "2026-08-10";

test("a practice cycle scores against the revealed day", async ({ page }) => {
  await signIn(page);
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

// Spec A1 §6: the typed intake in practice — impressions alone
// activate the description channel, so a round with no strokes
// scores, and the report row carries the typed text back.
test("typed impressions score without strokes", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/practice");
  await page.getByLabel("practice day").selectOption(PRACTICE_DAY);
  const scoreButton = page.getByRole("button", { name: "Score now" });
  await expect(scoreButton).toBeDisabled();
  const input = page.getByPlaceholder(/one impression/);
  await input.fill("tall vertical structure");
  await input.press("Enter");
  await expect(scoreButton).toBeEnabled();
  await scoreButton.click();
  await expect(page.getByText(/beat \d+ of \d+ decoys/)).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByText("What matched")).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "tall vertical structure" }),
  ).toBeVisible();
});

test("grouped strokes ride the practice record", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/practice");
  await page.getByLabel("practice day").selectOption(PRACTICE_DAY);
  await drawStroke(page, [0.3, 0.6], [0.7, 0.4]);
  await drawStroke(page, [0.4, 0.3], [0.6, 0.7]);
  await page.getByRole("button", { name: "Select strokes" }).click();
  // The first stroke passes through the canvas centre.
  const [x, y] = await canvasPoint(page, [0.5, 0.5]);
  await page.mouse.click(x, y);
  await page.getByPlaceholder(/what is it/).fill("tower");
  const sent = page.waitForRequest((request) =>
    request.url().includes("/api/practice/score"),
  );
  await page.getByRole("button", { name: "Group" }).click();
  await expect(page.getByText(/g1 · \d+ strokes/)).toBeVisible();
  await page.getByRole("button", { name: "Score now" }).click();
  const request = await sent;
  const body = request.postDataJSON() as {
    record: { groups: Array<{ id: string; label: string }> };
  };
  expect(body.record.groups).toEqual([{ id: "g1", label: "tower" }]);
  await expect(page.getByText(/beat \d+ of \d+ decoys/)).toBeVisible({
    timeout: 60_000,
  });
});
