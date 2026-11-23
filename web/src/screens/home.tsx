/**
 * The home screen (spec BR1 §6; the poster design of 2026-11-21): one
 * clear next step. The code of the day is the whole first screen, with
 * the one primary button under it. The day follows its status: start,
 * sent, being scored, results in.
 *
 * Over the code stands the streak, as a crown of stars: one star for
 * each day in a row, and a ring for today (ui/streak-crown.tsx). The
 * epigraph ends the screen. Behind the words is a quiet sky with the
 * player's own past sketches, faint (ui/home-sky.tsx).
 *
 * Nothing follows the first screen: the streak is here and in the bar,
 * practice is under Play, and each result is on Your results. A player
 * with no result yet also sees how the game works.
 *
 * Nothing here has a box: the day's button is the one filled thing.
 */

import { ArrowRight, CaretRight } from "@phosphor-icons/react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useRef, useState } from "react";

import { useApi } from "../api/client";
import { useDayQuery } from "../api/day-query";
import type { DayView, HistoryDayRow, HistoryView } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { type Figure, figureOf, seedOf } from "../sky/core";
import { CROWN_DAYS, CROWN_DAYS_NARROW, crownDays } from "../sky/home";
import { DayCode } from "../ui/code-cells";
import { useRemaining } from "../ui/countdown";
import type { DayNames } from "../ui/day-names";
import { useDayNames } from "../ui/day-names";
import {
  formatCloseClock,
  formatCloseMoment,
  formatRemaining,
} from "../ui/format";
import { HomeSky, type SkySketch } from "../ui/home-sky";
import { useNarrow } from "../ui/narrow";
import { isPostClose } from "../ui/pick-copy";
import { ResolveText } from "../ui/resolve-text";
import { SendCount } from "../ui/send-count";
import { ShareSketchButton } from "../ui/share-button";
import { type CrownToday, StreakCrown } from "../ui/streak-crown";
import { EpigraphFigure } from "./epigraph-figure";
import { EPIGRAPHS } from "./epigraphs";
import { pickGreeting } from "./greeting";
import { HowItWorksSteps, Premise } from "./how";

/**
 * How many of the latest revealed days the screen reads a sketch for:
 * the days the crown can draw. The same sketches stand behind the
 * words. A stored send does not change, so one read serves the visit,
 * and the result screen of a day shares the same cache entry.
 */
const SKETCH_DAYS = CROWN_DAYS;

/** The sketches of the latest revealed days, each as a constellation. */
function useSketches(rows: ReadonlyArray<HistoryDayRow>): SkySketch[] {
  const api = useApi();
  const sends = useQueries({
    queries: rows.map((row) => ({
      queryKey: ["submission", row.day],
      queryFn: () => api.getSubmission(row.day),
      staleTime: Number.POSITIVE_INFINITY,
      retry: false,
    })),
  });
  // A figure is drawn one time for each stored sketch.
  const kept = useRef(
    new Map<string, { strokes: unknown; figure: Figure | null }>(),
  );
  const sketches: SkySketch[] = [];
  rows.forEach((row, index) => {
    const strokes = sends[index]?.data?.record.canvas_strokes;
    if (strokes === undefined) {
      return;
    }
    let held = kept.current.get(row.day);
    if (held === undefined || held.strokes !== strokes) {
      held = { strokes, figure: figureOf(strokes) };
      kept.current.set(row.day, held);
    }
    if (held.figure !== null) {
      sketches.push({ day: row.day, p: row.p, figure: held.figure });
    }
  });
  return sketches;
}

/**
 * The newest revealed day the player sent on: the day the streak ends
 * at. A streak above zero has a stored send on that day, so the day is
 * in the history, with a result or as a day that was not scored.
 */
function newestSent(history: HistoryView | undefined): string | undefined {
  if (history === undefined) {
    return undefined;
  }
  const days = [
    ...history.days.map((row) => row.day),
    ...history.not_scored.map((row) => row.day),
  ];
  return days.reduce<string | undefined>(
    (newest, day) => (newest === undefined || day > newest ? day : newest),
    undefined,
  );
}

/** Today's place on the crown. It says only whether the player sent (I7). */
function crownToday(day: DayView | undefined): CrownToday {
  if (day === undefined || day.status === "revealed") {
    return null;
  }
  if (day.submitted) {
    return "sent";
  }
  return day.status === "open" ? "waiting" : "missed";
}

export function HomeScreen(): React.JSX.Element {
  const api = useApi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  // One greeting for the visit, drawn when the screen opens (spec H1 §5).
  const [greeting] = useState(() =>
    pickGreeting(new Date().getHours(), Math.random),
  );
  const day = useDayQuery();
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api.getHistory(),
  });
  const narrow = useNarrow();
  const rows = history.data?.days ?? [];
  const sketches = useSketches(rows.slice(0, SKETCH_DAYS));

  const firstTime =
    history.data !== undefined &&
    history.data.days.length === 0 &&
    day.data?.submitted !== true;
  const streak = me.data?.streak ?? 0;
  const results = new Map(rows.map((row) => [row.day, row.p]));
  const crown = crownDays(
    streak,
    newestSent(history.data),
    results,
    narrow ? CROWN_DAYS_NARROW : CROWN_DAYS,
  );
  const figureFor = (label: string): Figure | null =>
    sketches.find((each) => each.day === label)?.figure ?? null;

  return (
    <div className="home">
      <section className="home-poster">
        <HomeSky
          seed={seedOf(me.data?.player ?? "")}
          sketches={sketches}
          narrow={narrow}
        />
        <h1 className="home-greet">
          <ResolveText text={greeting} />
          {me.data === undefined ? null : (
            <ResolveText text={`, ${me.data.player}`} />
          )}
        </h1>
        {me.data === undefined ? null : (
          <StreakCrown
            streak={streak}
            days={crown}
            figureOf={figureFor}
            today={crownToday(day.data)}
          />
        )}
        <TodayCard
          day={day.data}
          pending={day.isPending}
          error={day.isError ? day.error : null}
        />
        <div className="home-epigraph">
          <EpigraphFigure epigraphs={EPIGRAPHS} />
        </div>
      </section>

      {firstTime ? (
        <section className="card home-first" aria-labelledby="first-how">
          <div className="row-between">
            <h2 id="first-how">New here? Here's how it works</h2>
            <Link to="/how" className="foot-link">
              More detail
              <ArrowRight size={18} aria-hidden="true" />
            </Link>
          </div>
          <Premise />
          <HowItWorksSteps protocol={day.data?.protocol} />
        </section>
      ) : (
        <Link to="/how" className="row-link home-how">
          How it works
          <CaretRight size={16} aria-hidden="true" />
        </Link>
      )}
    </div>
  );
}

/**
 * The line under the greeting. The day in play has no calendar date: it
 * is "today", with the countdown and the close in the reader's zone
 * while the close time is known. A day that is not open reads as the
 * local date on which it started (ui/day-names.ts).
 */
function eyebrowText(
  day: DayView,
  remaining: number | null,
  names: DayNames,
): string {
  if (day.status !== "open") {
    return names.long(day.day);
  }
  if (remaining !== null && typeof day.closes_at === "string") {
    const now = Date.parse(day.closes_at) - remaining;
    return `Today closes in ${formatRemaining(remaining)} (${formatCloseClock(day.closes_at, now)})`;
  }
  const close = formatCloseMoment(day.closes_at);
  return close === null ? "Today" : `Today, ${close}`;
}

function DayEyebrow(props: { day: DayView }): React.JSX.Element {
  const { day } = props;
  const remaining = useRemaining(day.closes_at);
  const names = useDayNames();
  return <p className="eyebrow">{eyebrowText(day, remaining, names)}</p>;
}

function TodayCard(props: {
  day: DayView | undefined;
  pending: boolean;
  error: unknown;
}): React.JSX.Element {
  const { day, pending, error } = props;
  if (pending) {
    return (
      <section className="home-today" aria-busy="true">
        <p className="subtle">Loading today…</p>
      </section>
    );
  }
  if (day === undefined) {
    return (
      <section className="home-today">
        {isRefusal(error) ? (
          <>
            <h2>No day is open right now</h2>
            <p className="muted">
              The next day starts soon. Meanwhile, practice on a past photo.
            </p>
          </>
        ) : (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(error)}
          </div>
        )}
      </section>
    );
  }
  if (day.status === "revealed") {
    return (
      <section className="home-today">
        <DayEyebrow day={day} />
        <DayCode code={day.trial_code} large />
        <h2>The photo is revealed</h2>
        {day.submitted ? null : (
          <p className="muted">
            You didn't send this one, but you can still see the photo.
          </p>
        )}
        <div className="home-cta">
          <Link to="/reveal" className="btn btn-primary btn-large">
            {day.submitted ? "See your result" : "See the photo"}
          </Link>
          <SendCount day={day} className="muted" testId="send-count" />
        </div>
      </section>
    );
  }
  if (day.status === "closing" || day.status === "closed") {
    return (
      <section className="home-today">
        <DayEyebrow day={day} />
        <DayCode code={day.trial_code} large />
        <h2>Today has closed</h2>
        <p className="muted">
          {day.submitted
            ? "Your sketch is in. Results are being worked out, and this page updates by itself."
            : "Results are being worked out, and this page updates by itself."}
        </p>
        <SendCount day={day} className="muted" testId="send-count" />
      </section>
    );
  }
  if (day.submitted) {
    return (
      <section className="home-today">
        <DayEyebrow day={day} />
        <DayCode code={day.trial_code} large />
        <h2>You're in for today</h2>
        <div className="home-cta">
          <Link to="/practice" className="btn btn-secondary">
            Practice while you wait
          </Link>
          <ShareSketchButton
            day={day.day}
            postClose={isPostClose(day.protocol)}
          />
          <SendCount day={day} className="muted" testId="send-count" />
        </div>
      </section>
    );
  }
  return (
    <section className="home-today" aria-labelledby="today-heading">
      <DayEyebrow day={day} />
      <DayCode code={day.trial_code} large />
      <h2 id="today-heading">
        {isPostClose(day.protocol)
          ? "Today's photo is picked after the close"
          : "Today's photo is hidden behind this code"}
      </h2>
      <div className="home-cta">
        <Link to="/today" className="btn btn-primary btn-large">
          Start today's sketch
        </Link>
        <SendCount day={day} className="muted" testId="send-count" />
      </div>
    </section>
  );
}
