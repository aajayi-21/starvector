/**
 * The results screen for one day (mock 1c, spec W1 B8; layout and
 * copy per spec BR1 §6). The eye goes to the result first — the
 * share of the other photos beaten, against the 50% guessing mark —
 * then to the hidden photo beside the sketch. The word matches and
 * the day's board follow, and the fairness check folds away.
 *
 * No "good match" wording anywhere (spec M1 §9 copy rules): the
 * screen states the result against chance and grades nothing.
 */

import { useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";

import { useApi } from "../api/client";
import type {
  ImageCredit,
  LeaderboardView,
  ReportRow,
  RevealView,
  TrialValue,
  WireRecord,
} from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { ReplayCanvas } from "../sketch/canvas";
import { AvatarCircle } from "../ui/avatar";
import { ChanceMeter } from "../ui/chance-meter";
import { formatDay, ordinal, percentBeaten } from "../ui/format";

function readSentCopy(day: string): WireRecord | null {
  try {
    const raw = window.localStorage.getItem(`sv:sent:${day}`);
    return raw === null ? null : (JSON.parse(raw) as WireRecord);
  } catch {
    return null;
  }
}

export function RevealScreen(): React.JSX.Element {
  const api = useApi();
  const search = useSearch({ from: "/reveal" });
  const reveal = useQuery({
    queryKey: ["reveal", search.day ?? "latest"],
    queryFn: () => api.getReveal(search.day),
  });

  if (reveal.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading results…
      </p>
    );
  }
  if (reveal.isError || reveal.data === undefined) {
    return (
      <div className="page-narrow" style={{ margin: "0 auto" }}>
        <section className="card card-hero">
          <h2>Results aren't in yet</h2>
          {isRefusal(reveal.error) ? (
            <p className="muted">
              The photo is revealed when the day closes and the results are
              worked out.
            </p>
          ) : (
            <div className="notice notice-bad" role="alert">
              {friendlyMessage(reveal.error)}
            </div>
          )}
          <div>
            <Link to="/" className="btn btn-secondary">
              Back to home
            </Link>
          </div>
        </section>
      </div>
    );
  }
  return <RevealBody view={reveal.data} />;
}

function RevealBody(props: { view: RevealView }): React.JSX.Element {
  const api = useApi();
  const { view } = props;
  const leaderboard = useQuery({
    queryKey: ["leaderboard", view.day],
    queryFn: () => api.getLeaderboard(view.day),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const submission = useQuery({
    queryKey: ["submission", view.day],
    queryFn: () => api.getSubmission(view.day),
    retry: false,
  });

  const sentCopy = readSentCopy(view.day);
  const replayRecord = submission.data?.record ?? sentCopy;
  const trial = view.trial;

  return (
    <div className="stack-lg">
      <div className="page-header" style={{ marginBottom: 0 }}>
        <div className="eyebrow">Results · {formatDay(view.day)}</div>
        <h1>
          {trial === null
            ? "The hidden photo"
            : `You beat ${percentBeaten(trial.p)}% of the photos`}
        </h1>
      </div>

      <div className="result-hero">
        <section className="card card-hero" aria-label="Your result">
          {trial === null ? (
            <p className="muted">
              You didn't send a sketch this day, so there's no result — but
              here's the photo that was hidden.
            </p>
          ) : (
            <ResultSummary trial={trial} />
          )}
        </section>
        <div className="pictures">
          <figure className="picture" style={{ margin: 0 }}>
            <div className="picture-frame">
              <img
                src={api.imageUrl(view.target_id)}
                alt={
                  view.credit?.title ??
                  `Hidden target of ${formatDay(view.day)}`
                }
              />
            </div>
            <figcaption className="stack-sm">
              <span style={{ fontWeight: 600 }}>The hidden photo</span>
              <Credit credit={view.credit} />
            </figcaption>
          </figure>
          <figure className="picture" style={{ margin: 0 }}>
            <div
              className="picture-frame"
              style={{ background: "var(--canvas)" }}
            >
              <SketchReplay
                record={replayRecord ?? null}
                loading={submission.isPending && sentCopy === null}
                sent={trial !== null}
              />
            </div>
            <figcaption>
              <span style={{ fontWeight: 600 }}>Your sketch</span>
            </figcaption>
          </figure>
        </div>
      </div>

      <div className="two-columns">
        {view.report.length === 0 ? (
          <section className="card">
            <h2>What connected</h2>
            <p className="muted">
              {trial === null
                ? "No words to match this day."
                : "You didn't add words this day, so only your sketch was compared."}
            </p>
          </section>
        ) : (
          <WordMatches rows={view.report} />
        )}
        <DayBoard
          view={leaderboard.data}
          pending={leaderboard.isPending}
          self={me.data?.player ?? ""}
        />
      </div>

      <Fairness view={view} />
    </div>
  );
}

/**
 * The player's sketch for the day: nothing while the stored copy
 * loads, the replay once it is here, and a plain line when there is
 * none — never a "not stored" line that flickers before the load.
 */
function SketchReplay(props: {
  record: WireRecord | null;
  loading: boolean;
  sent: boolean;
}): React.JSX.Element | null {
  if (props.loading) {
    return null;
  }
  if (props.record === null) {
    return (
      <p className="small" style={{ color: "#b3bccb", padding: 16, margin: 0 }}>
        {props.sent
          ? "Your sketch isn't stored on this device."
          : "No sketch this day."}
      </p>
    );
  }
  return <ReplayCanvas strokes={props.record.canvas_strokes} />;
}

function ResultSummary(props: { trial: TrialValue }): React.JSX.Element {
  const { trial } = props;
  const percent = percentBeaten(trial.p);
  const total = trial.decoy_count + 1;
  return (
    <div className="stack">
      <div className="big-number">{percent}%</div>
      <p style={{ fontSize: 17 }}>
        Your sketch matched the hidden photo better than{" "}
        <strong>
          {trial.beaten} of the other {trial.decoy_count}
        </strong>{" "}
        photos.
      </p>
      <ChanceMeter p={trial.p} />
      <p className="muted small">
        The hidden photo was your {ordinal(trial.target_rank)}-closest match out
        of {total}. Guessing averages 50%, and one day says little on its own —{" "}
        <Link to="/history">your results</Link> combine many days.
      </p>
    </div>
  );
}

export function Credit(props: {
  credit: ImageCredit | null;
}): React.JSX.Element {
  if (props.credit === null) {
    return <span className="subtle tiny">Photo from the Starvector set.</span>;
  }
  return (
    <span className="subtle tiny">
      “{props.credit.title}” from{" "}
      <a href={props.credit.page} target="_blank" rel="noreferrer noopener">
        {props.credit.source}
      </a>{" "}
      — see the page for the author and license.
    </span>
  );
}

/**
 * The words that connected. A matched word's bar is its matched mass
 * times the similarity of the pairing — how much it counted and how
 * close the pair was. A word with no match holds its mass in the
 * reserve bin (core/types.py MatchRow): it counted for nothing, so it
 * gets no bar and comes last.
 */
export function WordMatches(props: {
  rows: ReadonlyArray<ReportRow>;
}): React.JSX.Element {
  const strength = (row: ReportRow): number =>
    row.element === null ? 0 : Math.max(0, row.weight * row.similarity);
  const matched = props.rows
    .filter((row) => row.element !== null)
    .sort((a, b) => strength(b) - strength(a));
  const unmatched = props.rows.filter((row) => row.element === null);
  const most = Math.max(...matched.map(strength), 1e-9);
  return (
    <section className="card" aria-labelledby="words-matched">
      <div className="stack-sm">
        <h2 id="words-matched">What connected</h2>
        <p className="hint">
          Each word you wrote is paired with the closest detail listed for the
          photo. A longer bar means a closer pairing that counted for more. Your
          drawing's overall shape is compared too; that part isn't broken down
          here.
        </p>
      </div>
      <ul
        className="stack"
        style={{ margin: 0, padding: 0, listStyle: "none" }}
      >
        {matched.map((row) => {
          const share = Math.round((strength(row) / most) * 100);
          return (
            <li key={row.atom_id} className="stack-sm">
              <span>
                <strong>“{row.atom_text}”</strong>{" "}
                <span className="muted">→ {row.element}</span>
              </span>
              <div
                className="meter"
                style={{ height: 8 }}
                role="img"
                aria-label={`${share}% as strong as your strongest word`}
              >
                <div
                  className="meter-fill"
                  style={{ width: `${Math.max(2, share)}%` }}
                />
              </div>
            </li>
          );
        })}
        {unmatched.map((row) => (
          <li key={row.atom_id}>
            <strong>“{row.atom_text}”</strong>{" "}
            <span className="subtle">had no close match in this photo</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DayBoard(props: {
  view: LeaderboardView | undefined;
  pending: boolean;
  self: string;
}): React.JSX.Element {
  const { view, pending, self } = props;
  return (
    <section className="card" aria-labelledby="day-board">
      <h2 id="day-board">Everyone this day</h2>
      {pending ? (
        <p className="subtle">Loading…</p>
      ) : view === undefined || view.rows.length === 0 ? (
        <p className="muted">No other results this day.</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Player</th>
                <th className="num">Result</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr
                  key={row.player}
                  className={row.player === self ? "is-you" : undefined}
                >
                  <td>
                    <span
                      className="row"
                      style={{ gap: 8, flexWrap: "nowrap" }}
                    >
                      <AvatarCircle
                        player={row.player}
                        displayName={row.display_name}
                        avatarHash={row.avatar_hash}
                        size={24}
                      />
                      <span>
                        {row.player === self ? "You" : row.display_name}
                      </span>
                    </span>
                  </td>
                  <td className="num">{percentBeaten(row.p)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Fairness(props: { view: RevealView }): React.JSX.Element {
  const { view } = props;
  const mono: React.CSSProperties = {
    fontFamily: "var(--mono)",
    fontSize: 13,
    wordBreak: "break-all",
    background: "var(--surface-2)",
    padding: "8px 10px",
    borderRadius: 8,
  };
  return (
    <details className="card disclosure">
      <summary>Check that this day was fair</summary>
      <div className="disclosure-body">
        <p className="muted small">
          When the day opened, the server published a fingerprint of the hidden
          photo. Anyone can recompute it from the photo's id and the secret
          below and see that it matches — so the photo couldn't be swapped after
          the sketches came in.
        </p>
        <div className="stack-sm">
          <span className="label">Fingerprint published at the start</span>
          <code style={mono}>{view.commitment}</code>
        </div>
        <div className="stack-sm">
          <span className="label">Photo id</span>
          <code style={mono}>{view.target_id}</code>
        </div>
        <div className="stack-sm">
          <span className="label">Secret</span>
          <code style={mono}>{view.secret}</code>
        </div>
        <div className="stack-sm">
          <span className="label">Check it yourself</span>
          <code style={mono}>
            printf '%s:%s' {view.target_id} {view.secret} | sha256sum
          </code>
        </div>
      </div>
    </details>
  );
}
