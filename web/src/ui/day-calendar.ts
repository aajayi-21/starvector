/**
 * The day calendar of the web app: when the day with a label starts and
 * closes, and which label runs at an instant. Pure functions that
 * mirror service/schedule.py (spec BR1 §3.3), with no browser object,
 * so the mock API and a unit test read them with no screen.
 */

const LABEL_RULE = /^(\d{4})-(\d{2})-(\d{2})$/;
const HOUR_RULE = /^([01]\d|2[0-3]):([0-5]\d)$/;
const HALF_DAY_MINUTES = 12 * 60;
const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;

/** The rollover hour "HH:MM" as minutes after midnight UTC, or null. */
function rolloverMinutes(closesAtUtc: string | null): number | null {
  const found = closesAtUtc === null ? null : HOUR_RULE.exec(closesAtUtc);
  return found === null ? null : Number(found[1]) * 60 + Number(found[2]);
}

/** Midnight UTC of a label, in milliseconds, or null for other text. */
export function labelMidnight(label: string): number | null {
  const found = LABEL_RULE.exec(label);
  if (found === null) {
    return null;
  }
  const [year, month, date] = [found[1], found[2], found[3]].map(Number) as [
    number,
    number,
    number,
  ];
  const midnight = Date.UTC(year, month - 1, date);
  // Date.UTC rolls "02-31" into March: a label must be a calendar date.
  return new Date(midnight).toISOString().slice(0, 10) === label
    ? midnight
    : null;
}

const labelOf = (ms: number): string => new Date(ms).toISOString().slice(0, 10);

/**
 * The instant the day with this label starts. A day runs for 24 hours
 * and ends at the rollover hour H in UTC: with H at 12:00 or after, the
 * day labeled D starts on D − 1 at H, and with H before 12:00 it starts
 * on D at H. Null when the hour is not set or the label is not a date.
 */
export function dayStart(
  label: string,
  closesAtUtc: string | null,
): Date | null {
  const minutes = rolloverMinutes(closesAtUtc);
  const midnight = labelMidnight(label);
  if (minutes === null || midnight === null) {
    return null;
  }
  const onLabel = midnight + minutes * MINUTE_MS;
  return new Date(minutes >= HALF_DAY_MINUTES ? onLabel - DAY_MS : onLabel);
}

/** The instant the day with this label closes: 24 hours after its start. */
export function dayClose(
  label: string,
  closesAtUtc: string | null,
): Date | null {
  const start = dayStart(label, closesAtUtc);
  return start === null ? null : new Date(start.getTime() + DAY_MS);
}

/**
 * The label of the day that runs at this instant. With no rollover
 * hour, the label is the UTC date of the instant.
 */
export function labelAt(instant: Date, closesAtUtc: string | null): string {
  const today = labelMidnight(labelOf(instant.getTime())) as number;
  const minutes = rolloverMinutes(closesAtUtc);
  if (minutes === null) {
    return labelOf(today);
  }
  const rolloverToday = today + minutes * MINUTE_MS;
  if (minutes >= HALF_DAY_MINUTES) {
    return labelOf(instant.getTime() < rolloverToday ? today : today + DAY_MS);
  }
  return labelOf(instant.getTime() >= rolloverToday ? today : today - DAY_MS);
}
