/**
 * Plain-language formatting (spec BR1 §6). Day labels are UTC dates
 * (spec BR1 §3), so a label formats in UTC and keeps its one name. A
 * label is an identifier and not the reader's calendar: a day that
 * closes at 22:00 UTC starts its label's run on the evening before, in
 * the Americas. So a screen about the day in play names its close in the
 * reader's zone (formatCloseMoment), and a past day keeps its label.
 */

const DAY_FORMAT = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

const SHORT_DAY_FORMAT = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

/** "2026-09-24" → "Thu, Sep 24". */
export function formatDay(day: string): string {
  const date = new Date(`${day}T12:00:00Z`);
  return Number.isNaN(date.getTime()) ? day : DAY_FORMAT.format(date);
}

/** "2026-09-24" → "Sep 24". */
export function formatShortDay(day: string): string {
  const date = new Date(`${day}T12:00:00Z`);
  return Number.isNaN(date.getTime()) ? day : SHORT_DAY_FORMAT.format(date);
}

/** An ISO instant → "Sep 24", in the reader's own zone. */
export function formatInstantDay(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
      }).format(date);
}

/**
 * A result as a whole percent of the other photos beaten. Rounded
 * down, so a result never reads better than it is: 99.6% shows 99%,
 * and 100% means every other photo was beaten.
 */
export function percentBeaten(p: number): number {
  return Math.max(0, Math.min(100, Math.floor(p * 100 + 1e-9)));
}

/** 1 → "1st", 22 → "22nd", 113 → "113th". */
export function ordinal(n: number): string {
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) {
    return `${n}th`;
  }
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

const CLOSE_MOMENT_FORMAT = new Intl.DateTimeFormat(undefined, {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

const CLOCK_FORMAT = new Intl.DateTimeFormat(undefined, {
  hour: "numeric",
  minute: "2-digit",
});

/** An ISO instant → "closes Sat 6:00 PM", or null when there is none. */
export function formatCloseMoment(
  closesAt: string | null | undefined,
): string | null {
  if (typeof closesAt !== "string") {
    return null;
  }
  const date = new Date(closesAt);
  return Number.isNaN(date.getTime())
    ? null
    : `closes ${CLOSE_MOMENT_FORMAT.format(date)}`;
}

/** An ISO instant → "6:00 PM", in the reader's own zone. */
export function formatLocalClock(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : CLOCK_FORMAT.format(date);
}

/**
 * The skill number as the average result it stands for. With skill s, a
 * result has the density s·p^(s−1) (architecture §17), and its mean is
 * s/(s+1): 1.00 is 50%, the average of pure guessing.
 */
export function skillAsPercent(skill: number): number {
  return Math.round((100 * skill) / (skill + 1));
}

/** Milliseconds → "5 h 12 min", "12 min", or "under a minute". */
export function formatRemaining(ms: number): string {
  if (ms < 60_000) {
    return "under a minute";
  }
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.floor((ms % 3_600_000) / 60_000);
  if (hours === 0) {
    return `${minutes} min`;
  }
  return minutes === 0 ? `${hours} h` : `${hours} h ${minutes} min`;
}

/** The median of a list: the mean of the two middle values when even. */
export function median(values: ReadonlyArray<number>): number | undefined {
  if (values.length === 0) {
    return undefined;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const half = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) {
    return sorted[half];
  }
  const low = sorted[half - 1];
  const high = sorted[half];
  return low === undefined || high === undefined ? undefined : (low + high) / 2;
}

/** "22:00" UTC → the same instant in the reader's zone, e.g. "6:00 PM". */
export function localTimeOfUtc(hhmm: string): string {
  const match = /^(\d{2}):(\d{2})$/.exec(hhmm);
  if (match === null) {
    return `${hhmm} UTC`;
  }
  const date = new Date(
    Date.UTC(2026, 0, 1, Number(match[1]), Number(match[2])),
  );
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
