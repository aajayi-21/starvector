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
  await expect(
    page.getByRole("heading", { name: "Skill number" }),
  ).toBeVisible();
  await expect(page.getByText(theta as string, { exact: true })).toBeVisible();
  // The hit number of spec AG1 shows the server's value.
  await expect(page.getByTestId("hit-number")).toHaveText(
    expected.skill.hit_number.toFixed(2),
  );
  const table = page.locator("section").filter({ hasText: "Every day" });
  await expect(table.locator("tbody tr")).toHaveCount(expected.days.length);
  await expect(
    table.getByRole("link", { name: "Details" }).first(),
  ).toBeVisible();
});

test("the sky holds a star for each day and opens one", async ({ page }) => {
  await signIn(page);
  await blockExternalHosts(page);
  const expected = await (
    await page.request.get("http://127.0.0.1:8199/api/history")
  ).json();
  const newest = expected.days[0];
  const beaten = `You beat ${Math.floor(newest.p * 100 + 1e-9)}% of the photos`;

  await page.goto("/history");
  const stars = page
    .getByRole("group", { name: "Your days, the oldest first" })
    .getByRole("button");
  // The sky holds the latest 60 days at most (sky/core.ts).
  await expect(stars).toHaveCount(Math.min(expected.days.length, 60));
  // The words of a day are out of sight, and empty, until a day opens.
  const plate = page.locator(".sky-plate");
  await expect(plate).toBeEmpty();

  // The keyboard opens a day. The newest day is the last star.
  await stars.last().focus();
  await page.keyboard.press("Enter");
  await expect(plate).toContainText(beaten);
  await expect(
    plate.getByRole("link", { name: "Photo and details" }),
  ).toHaveAttribute("href", `/reveal?day=${newest.day}`);
  await page.keyboard.press("Escape");
  await expect(plate).toBeEmpty();

  // A pointer opens a day too, with a press on its star.
  const box = await stars.last().boundingBox();
  if (box === null) {
    throw new Error("the star has no place on the screen");
  }
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await expect(plate).toContainText(beaten);

  // A scroll leaves the sky: the day closes, and the numbers follow.
  await page
    .getByRole("heading", { name: "Every day you've played" })
    .scrollIntoViewIfNeeded();
  await expect(plate).toBeEmpty();
  await expect(
    page.getByRole("heading", { name: "Skill number" }),
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
