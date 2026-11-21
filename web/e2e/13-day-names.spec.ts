import { expect, test } from "@playwright/test";

import { blockExternalHosts, signIn } from "./helpers";

// A reader in Los Angeles, where the fixture's day (rollover at 22:00
// UTC) starts on the afternoon before the date of its label.
test.use({ timezoneId: "America/Los_Angeles", locale: "en-US" });

/** The fixture server's rollover hour. Kept equal to serve_fixture.py. */
const ROLLOVER_UTC_HOURS = 22;

/**
 * The name of a day by the rule of spec BR1 §3.3, worked out here with
 * no code of the app: a label with a rollover hour at or after noon
 * starts on the date before it, at that hour, and the name is that
 * instant's date in the reader's zone.
 */
function expectedName(label: string): string {
  const start =
    Date.parse(`${label}T00:00:00Z`) - (24 - ROLLOVER_UTC_HOURS) * 3_600_000;
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "America/Los_Angeles",
  }).format(new Date(start));
}

test("an earlier day reads as the local date on which it started", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  const history = await (
    await page.request.get("http://127.0.0.1:8199/api/history")
  ).json();
  const label: string = history.days[0].day;
  const name = expectedName(label);
  // The rule moves the name off the UTC date of the label in this zone.
  const utcName = new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${label}T12:00:00Z`));
  expect(name).not.toBe(utcName);

  await page.goto("/history");
  await expect(
    page.getByRole("heading", { name: "Skill number" }),
  ).toBeVisible();
  // The label stays in the page as the identifier of the day.
  await expect(page.locator(`time[datetime="${label}"]`).first()).toHaveText(
    name,
  );

  await page.goto(`/reveal?day=${label}`);
  await expect(page.locator(`time[datetime="${label}"]`).first()).toHaveText(
    name,
  );
});

test("the day in play shows its close and no calendar date", async ({
  page,
}) => {
  await signIn(page);
  await blockExternalHosts(page);
  await page.goto("/today");
  const close = page.locator(".play-brief-close");
  await expect(close).toBeVisible();
  // The close is in the reader's zone: a clock with AM or PM, no UTC.
  await expect(close).toHaveText(/Closes (\w+ )?at \d{1,2}:\d{2}\s?[AP]M, in /);
  await expect(page.locator(".play-brief-date")).toHaveCount(0);
});
