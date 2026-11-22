/**
 * The days of the Play place, in a row (owner design of 2026-11-21):
 * today is the last day, and each earlier day is practice on that day's
 * photo. The arrows step one day at a time; the date between them opens
 * a calendar, and a press on a day goes there. This takes the place of
 * the switch between Today and Practice and of the list of days in
 * practice.
 *
 * Each view keeps its own path, so the browser's back button works:
 * today is `/today`, and an earlier day is `/practice?day=…`.
 *
 * The day in play has no calendar date (ui/day-names.ts): it reads
 * "Today". An earlier day reads as the local date on which it started,
 * and the calendar puts it on that date. Only days that are over are in
 * the calendar, with the day in play: the list is the server's list of
 * practice days.
 */

import { CalendarBlank, CaretLeft, CaretRight } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";

import { useApi } from "../api/client";
import type { CalendarDate, DayNames } from "./day-names";
import { useDayNames } from "./day-names";
import {
  compareMonths,
  dateKey,
  type Month,
  monthCells,
  monthOf,
  shiftMonth,
} from "./month-grid";

const WEEKDAYS = ["S", "M", "T", "W", "T", "F", "S"] as const;
const MONTH_NAME = new Intl.DateTimeFormat(undefined, {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

/** What a cell of the calendar holds: an earlier day, or the day in play. */
interface CalendarDay {
  /** The label of an earlier day, or null for the day in play. */
  day: string | null;
  date: CalendarDate;
  name: string;
}

function calendarDays(
  practice: ReadonlyArray<string>,
  today: string | undefined,
  names: DayNames,
): Map<string, CalendarDay> {
  const found = new Map<string, CalendarDay>();
  for (const day of practice) {
    const date = names.calendarDate(day);
    if (date !== null) {
      found.set(dateKey(date), { day, date, name: names.long(day) });
    }
  }
  const date = today === undefined ? null : names.calendarDate(today);
  if (date !== null) {
    found.set(dateKey(date), { day: null, date, name: "Today" });
  }
  return found;
}

function Calendar(props: {
  days: ReadonlyMap<string, CalendarDay>;
  /** The key of the day on the screen now. */
  shown: string | null;
  start: Month;
  canSurprise: boolean;
  onPick: (day: string | null) => void;
  onSurprise: () => void;
}): React.JSX.Element {
  const [month, setMonth] = useState(props.start);
  const all = [...props.days.values()].map((each) => monthOf(each.date));
  const first = all.reduce(
    (least, each) => (compareMonths(each, least) < 0 ? each : least),
    month,
  );
  const last = all.reduce(
    (most, each) => (compareMonths(each, most) > 0 ? each : most),
    month,
  );
  return (
    <div className="day-calendar" role="dialog" aria-label="Pick a day">
      <div className="day-calendar-head">
        <button
          type="button"
          className="btn btn-icon"
          aria-label="The month before"
          disabled={compareMonths(month, first) <= 0}
          onClick={() => setMonth((old) => shiftMonth(old, -1))}
        >
          <CaretLeft size={18} aria-hidden="true" />
        </button>
        <strong aria-live="polite">
          {MONTH_NAME.format(new Date(Date.UTC(month.year, month.month, 1)))}
        </strong>
        <button
          type="button"
          className="btn btn-icon"
          aria-label="The month after"
          disabled={compareMonths(month, last) >= 0}
          onClick={() => setMonth((old) => shiftMonth(old, 1))}
        >
          <CaretRight size={18} aria-hidden="true" />
        </button>
      </div>
      <div className="day-calendar-grid">
        {WEEKDAYS.map((letter, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: the weekdays never reorder.
          <span key={index} className="day-calendar-weekday" aria-hidden="true">
            {letter}
          </span>
        ))}
        {monthCells(month).map((date, index) => {
          if (date === null) {
            // biome-ignore lint/suspicious/noArrayIndexKey: the empty cells before the first date never reorder.
            return <span key={`lead-${index}`} />;
          }
          const key = dateKey(date);
          const held = props.days.get(key);
          if (held === undefined) {
            return (
              <span key={key} className="day-calendar-day is-off">
                {date.date}
              </span>
            );
          }
          return (
            <button
              key={key}
              type="button"
              className={
                held.day === null
                  ? "day-calendar-day is-today"
                  : "day-calendar-day"
              }
              aria-label={held.name}
              aria-pressed={key === props.shown}
              onClick={() => props.onPick(held.day)}
            >
              {date.date}
            </button>
          );
        })}
      </div>
      <div className="day-calendar-foot">
        <span className="subtle tiny">An earlier day is practice.</span>
        {props.canSurprise ? (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={props.onSurprise}
          >
            Surprise me
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function DayStepper(props: {
  /** Which view of Play holds the stepper. */
  view: "today" | "practice";
  /** The earlier day on the screen; null on today, or with no day yet. */
  day: string | null;
}): React.JSX.Element {
  const api = useApi();
  const navigate = useNavigate();
  const names = useDayNames();
  // The stepper stands in views that show a failed read ("No day is open
  // right now"). It must not ask again when it mounts: a new read would
  // put the screen back to loading, which takes the stepper away, and
  // the two would go round. The screen's own read keeps the day fresh.
  const today = useQuery({
    queryKey: ["day"],
    queryFn: () => api.getDay(),
    retryOnMount: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });
  // The key and the request of the practice screen: one read serves both.
  const practice = useQuery({
    queryKey: ["practice-days"],
    queryFn: () => api.getPracticeDays(),
    retryOnMount: false,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });
  const [open, setOpen] = useState(false);
  const frame = useRef<HTMLDivElement | null>(null);
  const dateButton = useRef<HTMLButtonElement | null>(null);
  const calendarId = useId();

  // The newest day first, as the server sends them.
  const earlier = (practice.data?.days ?? []).map((row) => row.day);
  const at = props.day === null ? -1 : earlier.indexOf(props.day);
  const onToday = props.view === "today";
  const before = onToday ? earlier[0] : at < 0 ? undefined : earlier[at + 1];
  const after = onToday ? undefined : at > 0 ? earlier[at - 1] : null;

  const go = (day: string | null): void => {
    setOpen(false);
    if (day === null) {
      void navigate({ to: "/today" });
    } else {
      // A step between two earlier days is one place in the history.
      void navigate({ to: "/practice", search: { day }, replace: !onToday });
    }
  };

  // A press outside the calendar, or Escape, closes it.
  useEffect(() => {
    if (!open) {
      return;
    }
    const onPress = (event: PointerEvent): void => {
      if (
        frame.current !== null &&
        event.target instanceof Node &&
        !frame.current.contains(event.target)
      ) {
        setOpen(false);
      }
    };
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setOpen(false);
        dateButton.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onPress);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPress);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const todayLabel = today.data?.day;
  const days = calendarDays(earlier, todayLabel, names);
  const shownDate = onToday
    ? todayLabel === undefined
      ? null
      : names.calendarDate(todayLabel)
    : props.day === null
      ? null
      : names.calendarDate(props.day);
  const newest = earlier[0];
  const fallback = newest === undefined ? null : names.calendarDate(newest);
  const startDate = shownDate ?? fallback;

  return (
    <div className="day-stepper" ref={frame}>
      <button
        type="button"
        className="btn btn-secondary day-step"
        aria-label="The day before"
        disabled={before === undefined}
        onClick={() => {
          if (before !== undefined) {
            go(before);
          }
        }}
      >
        <CaretLeft size={18} aria-hidden="true" />
      </button>
      <button
        type="button"
        ref={dateButton}
        className="day-date"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? calendarId : undefined}
        disabled={startDate === null}
        onClick={() => setOpen((old) => !old)}
      >
        <span>
          <strong>{onToday ? "Today" : "Practice"}</strong>
          {onToday || props.day === null ? null : (
            <> · {names.long(props.day)}</>
          )}
        </span>
        <CalendarBlank size={16} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="btn btn-secondary day-step"
        aria-label="The day after"
        disabled={after === undefined}
        onClick={() => {
          if (after !== undefined) {
            go(after);
          }
        }}
      >
        <CaretRight size={18} aria-hidden="true" />
      </button>
      {onToday ? null : (
        <button
          type="button"
          className="btn btn-ghost day-today"
          onClick={() => go(null)}
        >
          Today
        </button>
      )}
      {open && startDate !== null ? (
        <div id={calendarId}>
          <Calendar
            days={days}
            shown={shownDate === null ? null : dateKey(shownDate)}
            start={monthOf(startDate)}
            canSurprise={earlier.length > 0}
            onPick={go}
            onSurprise={() => {
              const picked =
                earlier[Math.floor(Math.random() * earlier.length)];
              if (picked !== undefined) {
                go(picked);
              }
            }}
          />
        </div>
      ) : null}
    </div>
  );
}
