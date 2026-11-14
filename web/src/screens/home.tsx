/**
 * The home screen (spec BR1 §6): one clear next step. The hero card
 * follows the day's status — start, sent, being scored, results in —
 * and holds the one primary button on the screen. Below it, the last
 * result against chance, the streak, and practice. A player with no
 * result yet also sees how the game works.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useApi } from "../api/client";
import { useDayQuery } from "../api/day-query";
import type { DayView, HistoryView, MeView } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { ChanceMeter } from "../ui/chance-meter";
import { CodeCells } from "../ui/code-cells";
import { ClosesIn } from "../ui/countdown";
import {
  formatCloseMoment,
  formatDay,
  formatShortDay,
  percentBeaten,
  sendCountText,
} from "../ui/format";
import { ResolveText } from "../ui/resolve-text";
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

  return (
    <div className="stack-lg">
      <div className="page-header" style={{ marginBottom: 0 }}>
        <h1>
          <ResolveText text={greeting} />
          {me.data === undefined ? null : (
            <ResolveText text={`, ${me.data.player}`} />
          )}
        </h1>
      </div>
      <EpigraphFigure epigraphs={EPIGRAPHS} />

      <TodayCard
        day={day.data}
        pending={day.isPending}
        error={day.isError ? day.error : null}
      />

      {firstTime ? (
        <section className="card" aria-labelledby="first-how">
          <div className="row-between">
            <h2 id="first-how">New here? Here's how it works</h2>
            <Link to="/how" className="btn btn-ghost">
              More detail
            </Link>
          </div>
          <Premise />
          <HowItWorksSteps />
        </section>
      ) : null}

      <div className="cards">
        <LastResultCard history={history.data} />
        <StreakCard me={me.data} />
        <section className="card" aria-labelledby="practice-card">
          <h3 id="practice-card">Practice</h3>
          <p className="muted small">
            Replay a past photo and see how you'd have done. Nothing is saved.
          </p>
          <div className="spacer" />
          <Link to="/practice" className="btn btn-secondary">
            Practice now
          </Link>
        </section>
      </div>
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

function TodayCard(props: {
  day: DayView | undefined;
  pending: boolean;
  error: unknown;
}): React.JSX.Element {
  const { day, pending, error } = props;
  if (pending) {
    return (
      <section className="card card-hero" aria-busy="true">
        <p className="subtle">Loading today's session…</p>
      </section>
    );
  }
  if (day === undefined) {
    return (
      <section className="card card-hero">
        {isRefusal(error) ? (
          <>
            <h2>No session is open right now</h2>
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
  const eyebrow = `Today · ${formatCloseMoment(day.closes_at) ?? formatDay(day.day)}`;
  if (day.status === "revealed") {
    return (
      <section className="card card-hero">
        <div className="eyebrow">{eyebrow}</div>
        <h2>The photo is revealed</h2>
        <p className="muted">
          {day.submitted
            ? "See the hidden photo next to your sketch, and how close you came."
            : "You didn't send this one, but you can still see the photo."}
        </p>
        <SendCount day={day} />
        <div>
          <Link to="/reveal" className="btn btn-primary btn-large">
            {day.submitted ? "See your result" : "See the photo"}
          </Link>
        </div>
      </section>
    );
  }
  if (day.status === "closing" || day.status === "closed") {
    return (
      <section className="card card-hero">
        <div className="eyebrow">{eyebrow}</div>
        <h2>Today's session has closed</h2>
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
      <section className="card card-hero">
        <div className="eyebrow">{eyebrow}</div>
        <h2>You're in for today</h2>
        <p className="muted">
          Your sketch is locked in. The photo is revealed when the day closes
          <ClosesIn closesAt={day.closes_at} prefix=" — in" />.
        </p>
        <SendCount day={day} />
        <div>
          <Link to="/practice" className="btn btn-secondary">
            Practice while you wait
          </Link>
        </div>
      </section>
    );
  }
  return (
    <section className="card card-hero" aria-labelledby="today-heading">
      <div className="home-hero">
        <div className="stack">
          <div className="eyebrow">{eyebrow}</div>
          <h2 id="today-heading" style={{ fontSize: 26 }}>
            Today's photo is hidden behind this code
          </h2>
          <CodeCells code={day.trial_code} />
          <p className="muted">
            Sketch and describe whatever comes to mind. You can send once.
          </p>
          <SendCount day={day} />
          <div className="row">
            <Link to="/today" className="btn btn-primary btn-large">
              Start today's session
            </Link>
            <span className="subtle small">
              <ClosesIn closesAt={day.closes_at} />
            </span>
          </div>
        </div>
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
          <div className="row" style={{ alignItems: "baseline" }}>
            <span style={{ fontSize: 36, fontWeight: 700 }} className="tabular">
              {percentBeaten(latest.p)}%
            </span>
            <span className="subtle small">{formatShortDay(latest.day)}</span>
          </div>
          <ChanceMeter p={latest.p} />
          <Link
            to="/reveal"
            search={{ day: latest.day }}
            className="btn btn-ghost"
            style={{ alignSelf: "flex-start" }}
          >
            See details
          </Link>
        </>
      )}
    </section>
  );
}

function StreakCard(props: { me: MeView | undefined }): React.JSX.Element {
  const streak = props.me?.streak ?? 0;
  return (
    <section className="card" aria-labelledby="streak-card">
      <h3 id="streak-card">Streak</h3>
      <div className="row" style={{ alignItems: "baseline" }}>
        <span style={{ fontSize: 36, fontWeight: 700 }} className="tabular">
          {streak}
        </span>
        <span className="subtle small">{streak === 1 ? "day" : "days"}</span>
      </div>
      <p className="muted small">
        {streak === 0
          ? "Send on consecutive days to build a streak."
          : "Send each day to keep it going."}
      </p>
    </section>
  );
}
