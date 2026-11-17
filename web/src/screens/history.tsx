/**
 * Your results (mock 1d, spec W1 B9; copy and the two repairs per
 * spec BR1 §6): the skill number in plain words, the streak, the
 * best and the typical result, the recent days against the 50%
 * guessing line, and each day with a link to its results.
 *
 * The two repairs of docs/final-push.md §7.2: the best result is the
 * best share beaten — ranks from pools of different sizes do not
 * compare — and the median of an even count is the mean of the two
 * middle values.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../api/client";
import type {
  HistoryDayRow,
  HistoryView,
  MeView,
  NotScoredRow,
} from "../api/types";
import { friendlyMessage } from "../api/types";
import {
  formatShortDay,
  median,
  ordinal,
  percentBeaten,
  skillAsPercent,
} from "../ui/format";
import { ShareResultButton } from "../ui/share-button";

const CHART_DAYS = 14;
/**
 * Below this many results the skill number is labeled an early
 * estimate. A display note only: the number itself is the server's,
 * and nothing is withheld or rounded.
 */
const EARLY_RESULTS = 5;

export function HistoryScreen(): React.JSX.Element {
  const api = useApi();
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api.getHistory(),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });

  return (
    <div className="stack-lg">
      <div className="page-header" style={{ marginBottom: 0 }}>
        <h1>Your results</h1>
        <p className="muted">
          Each day you've played, measured against chance.
        </p>
      </div>
      {history.isPending ? (
        <p className="subtle" aria-busy="true">
          Loading…
        </p>
      ) : history.isError || history.data === undefined ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(history.error)}
        </div>
      ) : history.data.days.length === 0 ? (
        <section className="card card-hero">
          <h2>No results yet</h2>
          <p className="muted">
            Your first result appears after your first day closes.
          </p>
          {history.data.not_scored.length > 0 ? (
            <p className="muted small" data-testid="not-scored-note">
              We couldn't score your send of{" "}
              {history.data.not_scored
                .map((row) => formatShortDay(row.day))
                .join(", ")}
              . It doesn't count toward your results.
            </p>
          ) : null}
          <div>
            <Link to="/today" className="btn btn-primary">
              Go to today's session
            </Link>
          </div>
        </section>
      ) : (
        <HistoryBody view={history.data} me={me.data ?? null} />
      )}
    </div>
  );
}

/** How often luck alone does this well, in words. */
export function luckSentence(evidenceP: number): string {
  if (evidenceP < 0.001) {
    return "Luck alone does this well less than 1 time in 1,000.";
  }
  const percent = Math.round(evidenceP * 100);
  if (percent < 1) {
    return "Luck alone does this well less than 1% of the time.";
  }
  if (percent >= 99) {
    return "Luck alone does at least this well almost every time.";
  }
  return `Luck alone does at least this well about ${percent}% of the time.`;
}

function bestOf(days: ReadonlyArray<HistoryDayRow>): HistoryDayRow | undefined {
  let best: HistoryDayRow | undefined;
  for (const row of days) {
    if (best === undefined || row.p > best.p) {
      best = row;
    }
  }
  return best;
}

function HistoryBody(props: {
  view: HistoryView;
  me: MeView | null;
}): React.JSX.Element {
  const { view } = props;
  const streak = props.me?.streak ?? 0;
  const best = bestOf(view.days);
  const typical = median(view.days.map((row) => row.p));
  const recent = view.days.slice(0, CHART_DAYS).reverse();

  return (
    <>
      <div className="cards">
        <section className="card card-hero" aria-labelledby="skill-heading">
          <h2 id="skill-heading" className="eyebrow" style={{ fontSize: 13 }}>
            Skill number
          </h2>
          {view.skill === null ? (
            <p className="muted">
              Your skill number appears after your first result.
            </p>
          ) : (
            <>
              <div className="big-number" style={{ fontSize: 52 }}>
                {view.skill.theta.toFixed(2)}
              </div>
              <p className="muted small">
                1.00 is chance, the same thing as averaging 50%. Yours is the
                same as averaging {skillAsPercent(view.skill.theta)}%. Based on{" "}
                {view.skill.n} {view.skill.n === 1 ? "result" : "results"}.
              </p>
              <p className="hint">
                The leaderboard shows a steadied version of this number, which
                stays near the middle until enough results back it. The two can
                differ.
              </p>
              <div className="row" style={{ alignItems: "baseline" }}>
                <span className="label">Hit number</span>
                <span
                  className="tabular"
                  style={{ fontSize: 22, fontWeight: 650 }}
                  data-testid="hit-number"
                >
                  {view.skill.hit_number.toFixed(2)}
                </span>
              </div>
              <p className="muted small">
                Chance is 1.00 here as well. Higher means more of your results
                land near the very top. The skill number rewards a steady edge,
                and the hit number rewards occasional strong hits.
              </p>
              {view.skill.n < EARLY_RESULTS ? (
                <p
                  className="badge badge-warn"
                  style={{ alignSelf: "flex-start" }}
                >
                  Early estimate — it swings a lot until you have more days
                </p>
              ) : null}
              <p className="small">{luckSentence(view.skill.evidence_p)}</p>
            </>
          )}
        </section>
        <StatCard
          label="Streak"
          value={`${streak}`}
          unit={streak === 1 ? "day" : "days"}
        />
        <StatCard
          label="Best result"
          value={best === undefined ? "—" : `${percentBeaten(best.p)}%`}
          unit={best === undefined ? "" : formatShortDay(best.day)}
        />
        <StatCard
          label="Typical result"
          value={typical === undefined ? "—" : `${percentBeaten(typical)}%`}
          unit="the middle of your results"
        />
      </div>

      <section className="card" aria-labelledby="recent-heading">
        <div className="stack-sm">
          <h2 id="recent-heading">Recent days</h2>
          <p className="hint">
            Each bar is one day, newest on the right. The dashed line is 50% —
            what guessing averages.
          </p>
        </div>
        <ResultBars days={recent} />
      </section>

      <section className="card" aria-labelledby="days-heading">
        <h2 id="days-heading">Every day</h2>
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Code</th>
                <th className="num">Result</th>
                <th className="num">Hidden photo's place</th>
                <th>
                  <span className="visually-hidden">Details and share</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {dayEntries(view).map((entry) =>
                entry.kind === "not-scored" ? (
                  <NotScoredLine key={entry.row.day} row={entry.row} />
                ) : (
                  <ScoredLine key={entry.row.day} row={entry.row} />
                ),
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function StatCard(props: {
  label: string;
  value: string;
  unit: string;
}): React.JSX.Element {
  return (
    <section className="card">
      <div className="eyebrow">{props.label}</div>
      <div className="row" style={{ alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 36, fontWeight: 700 }} className="tabular">
          {props.value}
        </span>
        <span className="subtle small">{props.unit}</span>
      </div>
    </section>
  );
}

function ResultBars(props: {
  days: ReadonlyArray<HistoryDayRow>;
}): React.JSX.Element {
  const { days } = props;
  return (
    <div
      className="bars"
      role="img"
      aria-label={`Results for the last ${days.length} days, oldest first: ${days
        .map((row) => `${formatShortDay(row.day)} ${percentBeaten(row.p)}%`)
        .join(", ")}.`}
    >
      <div className="bars-axis" aria-hidden="true">
        <span style={{ top: "0%" }}>100%</span>
        <span style={{ top: "50%" }}>50%</span>
        <span style={{ top: "100%" }}>0%</span>
      </div>
      <div className="bars-chance" style={{ top: "50%" }} aria-hidden="true" />
      {days.map((row) => (
        <div
          key={row.day}
          className={row.p < 0.5 ? "bar bar-below" : "bar"}
          title={`${formatShortDay(row.day)}: ${percentBeaten(row.p)}%`}
          style={{ height: `${Math.max(2, row.p * 100)}%` }}
        />
      ))}
    </div>
  );
}

type DayEntry =
  | { kind: "scored"; row: HistoryDayRow }
  | { kind: "not-scored"; row: NotScoredRow };

/** The scored days and the days with no score (spec CR1 §7), newest first. */
function dayEntries(view: HistoryView): DayEntry[] {
  const entries: DayEntry[] = [
    ...view.days.map((row) => ({ kind: "scored" as const, row })),
    ...view.not_scored.map((row) => ({ kind: "not-scored" as const, row })),
  ];
  return entries.sort((a, b) => (a.row.day < b.row.day ? 1 : -1));
}

function ScoredLine(props: { row: HistoryDayRow }): React.JSX.Element {
  const { row } = props;
  return (
    <tr>
      <td>{formatShortDay(row.day)}</td>
      <td style={{ fontFamily: "var(--mono)" }}>{row.trial_code}</td>
      <td className="num">{percentBeaten(row.p)}%</td>
      <td className="num">
        {ordinal(row.target_rank)} of {row.decoy_count + 1}
      </td>
      <td>
        <span className="row-actions">
          <Link to="/reveal" search={{ day: row.day }}>
            Details
          </Link>
          <ShareResultButton
            variant="icon"
            day={row.day}
            trialCode={row.trial_code}
            trial={row}
          />
        </span>
      </td>
    </tr>
  );
}

function NotScoredLine(props: { row: NotScoredRow }): React.JSX.Element {
  const { row } = props;
  return (
    <tr data-testid="not-scored-row">
      <td>{formatShortDay(row.day)}</td>
      <td style={{ fontFamily: "var(--mono)" }}>{row.trial_code}</td>
      <td className="num" colSpan={2}>
        Not scored
      </td>
      <td>
        <Link to="/reveal" search={{ day: row.day }}>
          Details
        </Link>
      </td>
    </tr>
  );
}
