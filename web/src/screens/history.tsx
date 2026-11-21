/**
 * Your results (mock 1d, spec W1 B9; copy and the two repairs per
 * spec BR1 §6): the skill number in plain words, the streak, the
 * best and the typical result, each day as a star against the 50%
 * guessing line, and each day with a link to its results.
 *
 * The screen opens as a sky (ui/results-sky.tsx, owner request of
 * 2026-11-21): each revealed day is its own sketch, drawn as a
 * constellation and sized by its result. A scroll down leaves the sky:
 * the stars settle into the chart of the days, and the numbers follow.
 *
 * Under the sky two columns share the width. The first leads with the
 * skill number on a scale whose middle is chance, and one line of what
 * it stands for; four single numbers follow on hairlines. The longer
 * explanations fold behind one row with their words unchanged: each
 * sentence is a claim about the scoring. The column states numbers and
 * no verdict. The second column holds the table of the days. Nothing
 * here has a box.
 *
 * The two repairs of docs/final-push.md §7.2: the best result is the
 * best share beaten — ranks from pools of different sizes do not
 * compare — and the median of an even count is the mean of the two
 * middle values.
 */

import { CaretRight } from "@phosphor-icons/react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useApi } from "../api/client";
import type {
  HistoryDayRow,
  HistoryView,
  MeView,
  NotScoredRow,
} from "../api/types";
import { friendlyMessage } from "../api/types";
import { SKY_DAYS } from "../sky/core";
import type { DayNames } from "../ui/day-names";
import { useDayNames } from "../ui/day-names";
import { median, ordinal, percentBeaten, skillAsPercent } from "../ui/format";
import { useNarrow } from "../ui/narrow";
import { type DaySketch, ResultsSky } from "../ui/results-sky";
import { ShareResultButton } from "../ui/share-button";

/**
 * How many days the list shows before the player asks for each one. A
 * layout limit only: the button under the list shows the rest.
 */
const LIST_DAYS = 12;
/**
 * Below this many results the skill number is labeled an early
 * estimate. A display note only: the number itself is the server's,
 * and nothing is withheld or rounded.
 */
const EARLY_RESULTS = 5;

export function HistoryScreen(): React.JSX.Element {
  const api = useApi();
  const names = useDayNames();
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api.getHistory(),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });

  // With a result, the sky is the head of the screen and holds the title.
  if (history.data !== undefined && history.data.days.length > 0) {
    return (
      <div className="results">
        <HistoryBody view={history.data} me={me.data ?? null} />
      </div>
    );
  }
  return (
    <div className="results results-plain">
      <header className="page-header">
        <h1 className="h-display">Your results</h1>
        <p className="muted results-lead">
          Each day you've played, measured against chance.
        </p>
      </header>
      {history.isPending ? (
        <p className="subtle" aria-busy="true">
          Loading…
        </p>
      ) : history.isError || history.data === undefined ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(history.error)}
        </div>
      ) : (
        <section className="card page-narrow">
          <h2>No results yet</h2>
          <p className="muted">
            Your first result appears after your first day closes.
          </p>
          {history.data.not_scored.length > 0 ? (
            <p className="muted small" data-testid="not-scored-note">
              We couldn't score your send of{" "}
              {history.data.not_scored
                .map((row) => names.short(row.day))
                .join(", ")}
              . It doesn't count toward your results.
            </p>
          ) : null}
          <div>
            <Link to="/today" className="btn btn-primary">
              Go to today's sketch
            </Link>
          </div>
        </section>
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
  const api = useApi();
  const names = useDayNames();
  const narrow = useNarrow();
  const [all, setAll] = useState(false);
  // The sketch of each day in the sky: the player's own stored send.
  // A stored send does not change, so one read serves the visit, and
  // the result screen of a day shares the same cache entry.
  const skyDays = view.days.slice(0, SKY_DAYS).map((row) => row.day);
  const sends = useQueries({
    queries: skyDays.map((day) => ({
      queryKey: ["submission", day],
      queryFn: () => api.getSubmission(day),
      staleTime: Number.POSITIVE_INFINITY,
      retry: false,
    })),
  });
  const sketchOf = (day: string): DaySketch => {
    const send = sends[skyDays.indexOf(day)];
    if (send?.data !== undefined) {
      return send.data.record.canvas_strokes;
    }
    // No stored send to read: the day keeps its star and has no drawing.
    return send?.isError === true ? null : undefined;
  };
  const streak = props.me?.streak ?? 0;
  const best = bestOf(view.days);
  const typical = median(view.days.map((row) => row.p));
  const entries = dayEntries(view);
  const listed = all ? entries : entries.slice(0, LIST_DAYS);

  return (
    <>
      <ResultsSky
        days={view.days}
        sketchOf={sketchOf}
        player={props.me?.player ?? ""}
      />
      <div className="results-grid results-numbers">
        <section className="skill" aria-labelledby="skill-heading">
          {view.skill === null ? (
            <>
              <h2 id="skill-heading">Skill number</h2>
              <p className="muted">
                Your skill number appears after your first result.
              </p>
            </>
          ) : (
            <>
              <div className="skill-top">
                <h2 id="skill-heading">Skill number</h2>
                <div className="figure skill-number">
                  {view.skill.theta.toFixed(2)}
                </div>
              </div>
              <SkillScale theta={view.skill.theta} />
              <p>
                1.00 is chance, the same thing as averaging 50%. Yours is the
                same as averaging {skillAsPercent(view.skill.theta)}%. Based on{" "}
                {view.skill.n} {view.skill.n === 1 ? "result" : "results"}.
              </p>
              <p className="muted">{luckSentence(view.skill.evidence_p)}</p>
              {view.skill.n < EARLY_RESULTS ? (
                <p className="badge badge-warn skill-early">
                  Early estimate — it swings a lot until you have more days
                </p>
              ) : null}
            </>
          )}
          <dl className="skill-figures">
            {view.skill === null ? null : (
              <Figure label="Hit number">
                <span data-testid="hit-number">
                  {view.skill.hit_number.toFixed(2)}
                </span>
              </Figure>
            )}
            <Figure
              label="Best result"
              unit={best === undefined ? "" : names.short(best.day)}
            >
              {best === undefined ? "—" : `${percentBeaten(best.p)}%`}
            </Figure>
            <Figure label="Typical result" unit="the middle of your results">
              {typical === undefined ? "—" : `${percentBeaten(typical)}%`}
            </Figure>
            <Figure label="Streak" unit={streak === 1 ? "day" : "days"}>
              {streak}
            </Figure>
          </dl>
          {view.skill === null ? null : (
            <details className="row-disclosure skill-more">
              <summary>
                What these numbers mean
                <span className="row-meta">
                  <CaretRight
                    size={16}
                    aria-hidden="true"
                    className="row-chevron"
                  />
                </span>
              </summary>
              <div className="row-body">
                <p className="muted small">
                  The leaderboard shows a steadied version of the skill number,
                  which stays near the middle until enough results back it. The
                  two can differ.
                </p>
                <p className="muted small">
                  For the hit number, chance is 1.00 as well. Higher means more
                  of your results land near the very top. The skill number
                  rewards a steady edge, and the hit number rewards occasional
                  strong hits.
                </p>
              </div>
            </details>
          )}
        </section>

        <section className="days" aria-labelledby="days-heading">
          <h2 id="days-heading">Every day you've played</h2>
          {narrow ? (
            <ul className="day-list" aria-label="Each day">
              {listed.map((entry) => (
                <DayRow key={entry.row.day} entry={entry} names={names} />
              ))}
            </ul>
          ) : (
            <div className="table-scroll days-table">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Code</th>
                    <th scope="col" className="num">
                      Result
                    </th>
                    <th scope="col" className="num">
                      Place
                    </th>
                    <th scope="col">
                      <span className="visually-hidden">Details and share</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {listed.map((entry) =>
                    entry.kind === "not-scored" ? (
                      <NotScoredLine
                        key={entry.row.day}
                        row={entry.row}
                        names={names}
                      />
                    ) : (
                      <ScoredLine
                        key={entry.row.day}
                        row={entry.row}
                        names={names}
                      />
                    ),
                  )}
                </tbody>
              </table>
            </div>
          )}
          {entries.length > LIST_DAYS && !all ? (
            <div className="days-more">
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => setAll(true)}
              >
                Show all {entries.length} days
              </button>
            </div>
          ) : null}
        </section>
      </div>
    </>
  );
}

/** One single number of the summary, with its name over it. */
function Figure(props: {
  label: string;
  unit?: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="skill-figure">
      <dt>{props.label}</dt>
      <dd>
        <span className="figure">{props.children}</span>
        {props.unit === undefined || props.unit === "" ? null : (
          <span className="skill-figure-unit">{props.unit}</span>
        )}
      </dd>
    </div>
  );
}

/** The two ends of the skill scale: half of chance and twice chance. */
const SCALE_LOW = 0.5;
const SCALE_HIGH = 2;

/**
 * Where a skill number sits against chance. The scale is in ratios, so
 * 1.00 is its middle, and a number beyond an end sits at that end. A
 * drawing of the number above it: it adds no fact and no verdict.
 */
function SkillScale(props: { theta: number }): React.JSX.Element {
  const span = Math.log(SCALE_HIGH) - Math.log(SCALE_LOW);
  const raw =
    (Math.log(Math.max(props.theta, 1e-6)) - Math.log(SCALE_LOW)) / span;
  const at = Math.max(0, Math.min(1, raw)) * 100;
  return (
    <div className="skill-scale">
      <div
        className="meter"
        role="img"
        aria-label={`Skill number ${props.theta.toFixed(2)}. 1.00 is chance.`}
      >
        <div className="meter-chance" />
        <div className="skill-dot" style={{ left: `${at}%` }} />
      </div>
      <div className="meter-scale" aria-hidden="true">
        <span>{SCALE_LOW.toFixed(2)}</span>
        <span>1.00, guessing</span>
        <span>{SCALE_HIGH.toFixed(2)}</span>
      </div>
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

function ScoredLine(props: {
  row: HistoryDayRow;
  names: DayNames;
}): React.JSX.Element {
  const { row } = props;
  return (
    <tr>
      <td>
        <time dateTime={row.day}>{props.names.long(row.day)}</time>
      </td>
      <td className="results-code">{row.trial_code}</td>
      <td className="num">{percentBeaten(row.p)}%</td>
      <td className="num nowrap muted">
        {ordinal(row.target_rank)} of {row.decoy_count + 1}
      </td>
      <td className="num">
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

function NotScoredLine(props: {
  row: NotScoredRow;
  names: DayNames;
}): React.JSX.Element {
  const { row } = props;
  return (
    <tr data-testid="not-scored-row">
      <td>
        <time dateTime={row.day}>{props.names.long(row.day)}</time>
      </td>
      <td className="results-code">{row.trial_code}</td>
      <td className="num muted" colSpan={2}>
        Not scored
      </td>
      <td className="num">
        <span className="row-actions">
          <Link to="/reveal" search={{ day: row.day }}>
            Details
          </Link>
        </span>
      </td>
    </tr>
  );
}

/**
 * One day on a phone: the whole row is the link to the day's results.
 * The share control is on that screen.
 */
function DayRow(props: {
  entry: DayEntry;
  names: DayNames;
}): React.JSX.Element {
  const { entry } = props;
  return (
    <li
      {...(entry.kind === "not-scored"
        ? { "data-testid": "not-scored-row" }
        : {})}
    >
      <Link to="/reveal" search={{ day: entry.row.day }} className="day-row">
        <span className="day-row-when">
          <time dateTime={entry.row.day}>
            {props.names.long(entry.row.day)}
          </time>
          <span className="results-code">{entry.row.trial_code}</span>
        </span>
        {entry.kind === "not-scored" ? (
          <span className="day-row-result muted">Not scored</span>
        ) : (
          <span className="day-row-result">
            <strong>{percentBeaten(entry.row.p)}%</strong>
            <span className="muted nowrap">
              {ordinal(entry.row.target_rank)} of {entry.row.decoy_count + 1}
            </span>
          </span>
        )}
        <CaretRight size={16} aria-hidden="true" />
      </Link>
    </li>
  );
}
