/**
 * The home screen (spec BR1 §6): one clear next step. The day comes
 * first, follows the day's status — start, sent, being scored, results
 * in — and holds the one primary button on the screen. Beside it, the
 * player's latest results stand as a line of stars over the epigraph;
 * on a phone the stars follow the day and the epigraph ends the page.
 * Below one hairline, the last result against chance, the streak, and
 * practice share the width as three columns, each with one link. A
 * player with no result yet also sees how the game works.
 *
 * Nothing here has a box: the day's button is the one filled thing.
 */

import { ArrowRight, CaretRight } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useApi } from "../api/client";
import { useDayQuery } from "../api/day-query";
import type { DayView, HistoryView } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { ChanceMeter } from "../ui/chance-meter";
import { DayCode } from "../ui/code-cells";
import { Constellation } from "../ui/constellation";
import { useRemaining } from "../ui/countdown";
import type { DayNames } from "../ui/day-names";
import { useDayNames } from "../ui/day-names";
import {
  formatCloseClock,
  formatCloseMoment,
  formatRemaining,
  percentBeaten,
} from "../ui/format";
import { useNarrow } from "../ui/narrow";
import { isPostClose } from "../ui/pick-copy";
import { ResolveText } from "../ui/resolve-text";
import { SendCount } from "../ui/send-count";
import { ShareSketchButton } from "../ui/share-button";
import { EpigraphFigure } from "./epigraph-figure";
import { EPIGRAPHS } from "./epigraphs";
import { pickGreeting } from "./greeting";
import { HowItWorksSteps, Premise } from "./how";

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

  const firstTime =
    history.data !== undefined &&
    history.data.days.length === 0 &&
    day.data?.submitted !== true;
  const streak = me.data?.streak ?? 0;
  const narrow = useNarrow();

  return (
    <div className="home">
      {/* Two columns on a wide screen: the day, and the sky. On a phone
          the two wrappers let go, and each part takes its place in one
          column by its order (styles/home.css). */}
      <div className="home-top">
        <div className="home-day">
          <h1 className="h-display">
            <ResolveText text={greeting} />
            {me.data === undefined ? null : (
              <ResolveText text={`, ${me.data.player}`} />
            )}
          </h1>
          <TodayCard
            day={day.data}
            pending={day.isPending}
            error={day.isError ? day.error : null}
          />
        </div>
        <div className="home-sky">
          <Constellation days={history.data?.days ?? []} narrow={narrow} />
          <div className="home-epigraph">
            <EpigraphFigure epigraphs={EPIGRAPHS} />
          </div>
        </div>
      </div>

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
      ) : null}

      <div className="columns home-cards">
        <LastResultCard history={history.data} />
        <StreakCard
          streak={streak}
          history={history.data}
          today={day.data?.day}
        />
        <section className="card" aria-labelledby="practice-card">
          <h3 id="practice-card">Practice</h3>
          <p className="muted">
            Replay a past photo and see how you'd have done. Nothing is saved.
          </p>
          <CardFoot to="/practice" label="Practice now" />
        </section>
      </div>

      {firstTime ? null : (
        <Link to="/how" className="row-link home-how">
          How it works
          <CaretRight size={16} aria-hidden="true" />
        </Link>
      )}
    </div>
  );
}

/** The one link that ends a home column: words and an arrow. */
function CardFoot(props: {
  to: "/practice" | "/history" | "/how" | "/reveal";
  label: string;
  day?: string;
}): React.JSX.Element {
  return (
    <div className="card-foot">
      <Link
        to={props.to}
        {...(props.day === undefined ? {} : { search: { day: props.day } })}
        className="foot-link"
      >
        {props.label}
        <ArrowRight size={18} aria-hidden="true" />
      </Link>
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
        <h2>The photo is revealed</h2>
        <p className="muted">
          {day.submitted
            ? `See ${isPostClose(day.protocol) ? "the photo" : "the hidden photo"} next to your sketch, and how close you came.`
            : "You didn't send this one, but you can still see the photo."}
        </p>
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
        <h2>You're in for today</h2>
        <p className="muted">
          Your sketch is locked in. The photo is revealed when the day closes.
        </p>
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
      <h2 id="today-heading">
        {isPostClose(day.protocol)
          ? "Today's photo is picked after the close"
          : "Today's photo is hidden behind this code"}
      </h2>
      <DayCode code={day.trial_code} large />
      <p className="home-lead">
        Sketch and describe whatever comes to mind. You get one send.
      </p>
      <div className="home-cta">
        <Link to="/today" className="btn btn-primary btn-large">
          Start today's sketch
        </Link>
        <SendCount day={day} className="muted" testId="send-count" />
      </div>
    </section>
  );
}

function LastResultCard(props: {
  history: HistoryView | undefined;
}): React.JSX.Element {
  const names = useDayNames();
  const latest = props.history?.days[0];
  return (
    <section className="card" aria-labelledby="last-result">
      <h3 id="last-result">Your last result</h3>
      {latest === undefined ? (
        <p className="muted">
          {props.history === undefined
            ? "Loading…"
            : "Your first result appears after your first day closes."}
        </p>
      ) : (
        <>
          <div className="home-card-value">
            <span className="home-card-number figure">
              {percentBeaten(latest.p)}%
            </span>
            <span className="muted">{names.short(latest.day)}</span>
          </div>
          <div className="home-meter">
            <ChanceMeter p={latest.p} />
          </div>
          <CardFoot to="/reveal" day={latest.day} label="See details" />
        </>
      )}
    </section>
  );
}

/** How many of the days before today the week row shows. */
const WEEK_DAYS = 7;

/** "2026-11-18" moved by a count of days. */
function shiftDay(day: string, by: number): string {
  const date = new Date(`${day}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + by);
  return date.toISOString().slice(0, 10);
}

interface WeekDay {
  /** The first letter of the weekday on which the day started. */
  letter: string;
  on: boolean;
}

/**
 * The seven days before today, oldest first: on where the player has a
 * revealed result. The row reads the history alone, which holds
 * revealed days only, so it says nothing of the open day (I7).
 */
function weekOf(
  history: HistoryView,
  today: string,
  names: DayNames,
): WeekDay[] {
  const played = new Set(history.days.map((row) => row.day));
  return Array.from({ length: WEEK_DAYS }, (_, index) => {
    const day = shiftDay(today, index - WEEK_DAYS);
    return {
      letter: names.weekdayLetter(day),
      on: played.has(day),
    };
  });
}

function StreakCard(props: {
  streak: number;
  history: HistoryView | undefined;
  today: string | undefined;
}): React.JSX.Element {
  const { streak, history, today } = props;
  const names = useDayNames();
  const week =
    history === undefined || today === undefined
      ? null
      : weekOf(history, today, names);
  return (
    <section className="card" aria-labelledby="streak-card">
      <h3 id="streak-card">Streak</h3>
      <div className="home-streak">
        <div className="home-card-value">
          <span className="home-card-number figure">{streak}</span>
          <span className="muted">{streak === 1 ? "day" : "days"}</span>
        </div>
        {week === null ? null : (
          <div>
            <div className="week-dots" aria-hidden="true">
              {week.map((each, index) => (
                <span
                  // The row is positional: the index is the day.
                  // biome-ignore lint/suspicious/noArrayIndexKey: see above
                  key={index}
                  className={each.on ? "week-day is-on" : "week-day"}
                >
                  <span className="week-dot" />
                  {each.letter}
                </span>
              ))}
            </div>
            <span className="visually-hidden">
              You have a result on {week.filter((each) => each.on).length} of
              the last {WEEK_DAYS} days.
            </span>
          </div>
        )}
      </div>
      <p className="muted">
        {streak === 0
          ? "Send on consecutive days to build a streak."
          : "Send each day to keep it going."}
      </p>
      <CardFoot to="/history" label="Your results" />
    </section>
  );
}
