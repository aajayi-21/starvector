/**
 * The home screen (spec BR1 §6): one clear next step. The day's card
 * comes first, follows the day's status — start, sent, being scored,
 * results in — and holds the one primary button on the screen. The
 * epigraph sits in the card's second column on a wide screen and at the
 * end of the page on a phone. Below the card, the last result against
 * chance, the streak, and practice share one footer line. A player with
 * no result yet also sees how the game works.
 */

import { ArrowRight, CaretRight, Clock } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useApi } from "../api/client";
import { useDayQuery } from "../api/day-query";
import type { DayView, HistoryView } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { ChanceMeter } from "../ui/chance-meter";
import { CodeCells } from "../ui/code-cells";
import { useRemaining } from "../ui/countdown";
import {
  formatCloseMoment,
  formatDay,
  formatLocalClock,
  formatRemaining,
  formatShortDay,
  percentBeaten,
  sendCountText,
} from "../ui/format";
import { isPostClose } from "../ui/pick-copy";
import { ResolveText } from "../ui/resolve-text";
import { streakLabel } from "../ui/streak";
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

  return (
    <div className="stack-lg">
      <div className="page-header home-greeting" style={{ marginBottom: 0 }}>
        <h1>
          <ResolveText text={greeting} />
          {me.data === undefined ? null : (
            <ResolveText text={`, ${me.data.player}`} />
          )}
        </h1>
        {/* The top bar hides its streak badge on a phone, so the
            greeting row holds the number there. */}
        {streak === 0 ? null : (
          <span className="show-narrow subtle small">
            {streakLabel(streak)}
          </span>
        )}
      </div>

      {/* One card on a wide screen: the day on the left, the epigraph
          on the right. On a phone the wrapper lets go of its two parts,
          the day keeps the card, and the epigraph moves to the end. */}
      <div className="card card-hero home-top">
        <TodayCard
          day={day.data}
          pending={day.isPending}
          error={day.isError ? day.error : null}
        />
        <div className="home-epigraph">
          <EpigraphFigure epigraphs={EPIGRAPHS} />
        </div>
      </div>

      {firstTime ? (
        <section className="card" aria-labelledby="first-how">
          <div className="row-between">
            <h2 id="first-how">New here? Here's how it works</h2>
            <Link to="/how" className="foot-link">
              More detail
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
          <Premise />
          <HowItWorksSteps protocol={day.data?.protocol} />
        </section>
      ) : null}

      <div className="cards home-cards">
        <LastResultCard history={history.data} />
        <StreakCard
          streak={streak}
          history={history.data}
          today={day.data?.day}
        />
        <section className="card" aria-labelledby="practice-card">
          <h3 id="practice-card">Practice</h3>
          <p className="muted small home-card-detail">
            Replay a past photo and see how you'd have done. Nothing is saved.
          </p>
          <CardFoot to="/practice" label="Practice now" />
        </section>
        {firstTime ? null : (
          <section className="card show-narrow" aria-labelledby="how-card">
            <h3 id="how-card">How it works</h3>
            <CardFoot to="/how" label="Read how it works" />
          </section>
        )}
      </div>
    </div>
  );
}

/**
 * The one footer line of a home card: a text link, flush with the
 * card's left edge. On a phone the card is a row and the link covers
 * the whole row.
 */
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
        <span className="foot-text">{props.label}</span>
        <ArrowRight size={16} aria-hidden="true" className="foot-arrow" />
        <CaretRight size={16} aria-hidden="true" className="foot-caret" />
      </Link>
    </div>
  );
}

/** The day's send count, in each hero state (spec H1 §3). */
function SendCount(props: { day: DayView }): React.JSX.Element {
  return (
    <p className="subtle small" data-testid="send-count">
      {sendCountText(props.day.sends, props.day.status === "open")}
    </p>
  );
}

/**
 * The line over the day's card. While the day is open and the close
 * time is known, it counts down; otherwise it says the close moment or
 * the date.
 */
function DayEyebrow(props: { day: DayView }): React.JSX.Element {
  const { day } = props;
  const remaining = useRemaining(day.closes_at);
  const text =
    day.status === "open" && remaining !== null
      ? `closes in ${formatRemaining(remaining)} (${formatLocalClock(day.closes_at as string)})`
      : (formatCloseMoment(day.closes_at) ?? formatDay(day.day));
  return (
    <div className="eyebrow eyebrow-icon">
      <Clock size={16} aria-hidden="true" />
      Today · {text}
    </div>
  );
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
          <SendCount day={day} />
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
        <SendCount day={day} />
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
          <SendCount day={day} />
        </div>
      </section>
    );
  }
  return (
    <section className="home-today" aria-labelledby="today-heading">
      <DayEyebrow day={day} />
      <h2 id="today-heading" className="home-title">
        {isPostClose(day.protocol)
          ? "Today's photo is picked after the close"
          : "Today's photo is hidden behind this code"}
      </h2>
      <CodeCells code={day.trial_code} />
      <p className="muted">
        Sketch and describe whatever comes to mind. You get one send.
      </p>
      <div className="home-cta">
        <Link to="/today" className="btn btn-primary btn-large">
          Start today's sketch
        </Link>
        <SendCount day={day} />
      </div>
    </section>
  );
}

function LastResultCard(props: {
  history: HistoryView | undefined;
}): React.JSX.Element {
  const latest = props.history?.days[0];
  return (
    <section className="card" aria-labelledby="last-result">
      <h3 id="last-result">Your last result</h3>
      {latest === undefined ? (
        <p className="muted small">
          {props.history === undefined
            ? "Loading…"
            : "Your first result appears after your first day closes."}
        </p>
      ) : (
        <>
          <div className="home-card-value">
            <span className="home-card-number tabular">
              {percentBeaten(latest.p)}%
            </span>
            <span className="subtle small">{formatShortDay(latest.day)}</span>
          </div>
          <div className="home-card-detail">
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

/**
 * The seven days before today, oldest first: true where the player has
 * a revealed result. The row reads the history alone, which holds
 * revealed days only, so it says nothing of the open day (I7).
 */
function weekOf(history: HistoryView, today: string): boolean[] {
  const played = new Set(history.days.map((row) => row.day));
  return Array.from({ length: WEEK_DAYS }, (_, index) =>
    played.has(shiftDay(today, index - WEEK_DAYS)),
  );
}

function StreakCard(props: {
  streak: number;
  history: HistoryView | undefined;
  today: string | undefined;
}): React.JSX.Element {
  const { streak, history, today } = props;
  const week =
    history === undefined || today === undefined
      ? null
      : weekOf(history, today);
  return (
    <section className="card" aria-labelledby="streak-card">
      <h3 id="streak-card">Streak</h3>
      <div className="home-card-value">
        <span className="home-card-number tabular">{streak}</span>
        <span className="subtle small">{streak === 1 ? "day" : "days"}</span>
      </div>
      {week === null ? null : (
        <div className="home-card-detail">
          <div className="week-dots" aria-hidden="true">
            {week.map((on, index) => (
              <span
                // The row is positional: the index is the day.
                // biome-ignore lint/suspicious/noArrayIndexKey: see above
                key={index}
                className={on ? "week-dot is-on" : "week-dot"}
              />
            ))}
          </div>
          <span className="visually-hidden">
            You have a result on {week.filter(Boolean).length} of the last{" "}
            {WEEK_DAYS} days.
          </span>
        </div>
      )}
      <p className="muted small home-card-detail">
        {streak === 0
          ? "Send on consecutive days to build a streak."
          : "Send each day to keep it going."}
      </p>
      <CardFoot to="/history" label="Your results" />
    </section>
  );
}
