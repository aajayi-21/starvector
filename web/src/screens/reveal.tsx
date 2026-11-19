/**
 * The results screen for one day (mock 1c, spec W1 B8; layout and
 * copy per spec BR1 §6). The heading states the result. The eye then
 * goes to the photo beside the sketch, which is the reason to open
 * the screen, and to the result against the 50% guessing mark. The
 * word matches and the day's board follow, and the fairness check
 * folds away: three plain steps first, the raw values behind a row.
 *
 * No "good match" wording anywhere (spec M1 §9 copy rules): the
 * screen states the result against chance and grades nothing.
 */

import {
  CaretRight,
  DownloadSimple,
  Lock,
  PencilSimpleLine,
  Shuffle,
} from "@phosphor-icons/react";
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
import { floorSentence, privateOwnRow } from "../board/core";
import { ReplayCanvas } from "../sketch/canvas";
import { AvatarCircle } from "../ui/avatar";
import { ChanceMeter } from "../ui/chance-meter";
import { formatDay, ordinal, percentBeaten } from "../ui/format";
import { isPostClose, photoNoun } from "../ui/pick-copy";
import { PrivateRowBadge } from "../ui/private-row-badge";
import { ShareResultButton } from "../ui/share-button";

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
            ? isPostClose(view.protocol)
              ? "The day's photo"
              : "The hidden photo"
            : `You beat ${percentBeaten(trial.p)}% of the photos`}
        </h1>
      </div>

      <div className="result-hero">
        <div className="pictures">
          <figure className="picture" style={{ margin: 0 }}>
            <div className="picture-frame">
              <img
                src={api.imageUrl(view.target_id)}
                alt={
                  view.credit?.title ??
                  `${isPostClose(view.protocol) ? "The photo" : "Hidden target"} of ${formatDay(view.day)}`
                }
              />
            </div>
            <figcaption className="stack-sm">
              <span style={{ fontWeight: 600 }}>
                {isPostClose(view.protocol) ? "The photo" : "The hidden photo"}
              </span>
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
        <section className="card card-hero" aria-label="Your result">
          {trial === null && view.quarantined ? (
            <p className="muted" data-testid="not-scored">
              We couldn't score your send this day. It doesn't count toward your
              results, and your streak still stands.
            </p>
          ) : trial === null ? (
            <p className="muted">
              You didn't send a sketch this day, so there's no result — but
              here's{" "}
              {isPostClose(view.protocol)
                ? "the day's photo"
                : "the photo that was hidden"}
              .
            </p>
          ) : (
            <ResultSummary
              trial={trial}
              day={view.day}
              protocol={view.protocol}
            />
          )}
        </section>
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

      {isPostClose(view.protocol) ? (
        <PulseFairness view={view} />
      ) : (
        <Fairness view={view} />
      )}
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

function ResultSummary(props: {
  trial: TrialValue;
  day: string;
  protocol: RevealView["protocol"];
}): React.JSX.Element {
  const { trial } = props;
  const noun = photoNoun(props.protocol);
  const total = trial.decoy_count + 1;
  return (
    <div className="stack">
      <p style={{ fontSize: 17 }}>
        Your sketch matched {noun} better than{" "}
        <strong>
          {trial.beaten} of the other {trial.decoy_count}
        </strong>{" "}
        photos.
      </p>
      <ChanceMeter p={trial.p} />
      <p className="muted small">
        {noun.charAt(0).toUpperCase() + noun.slice(1)} was your{" "}
        {ordinal(trial.target_rank)}-closest match out of {total}. Guessing
        averages 50%, and one day says little on its own —{" "}
        <Link to="/history">your results</Link> combine many days.
      </p>
      <div>
        <ShareResultButton day={props.day} trial={trial} />
      </div>
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
  // The caller's own row while it is below the floor of spec A2 §9.5.
  const hidden = view === undefined ? null : privateOwnRow(view.rows, self);
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
                        avatarHash={row.avatar_hash}
                        size={24}
                      />
                      <span>{row.player === self ? "You" : row.player}</span>
                    </span>
                    {row === hidden ? <PrivateRowBadge /> : null}
                  </td>
                  <td className="num">{percentBeaten(row.p)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {view === undefined || hidden === null ? null : (
        <p className="hint">{floorSentence(view.floor)}</p>
      )}
    </section>
  );
}

/** The look of a raw value in the fairness check. */
const MONO: React.CSSProperties = {
  fontFamily: "var(--mono)",
  fontSize: 13,
  wordBreak: "break-all",
  background: "var(--surface-2)",
  padding: "8px 10px",
  borderRadius: 8,
};

/** One step of the fairness check: an icon, a moment, and what held. */
function FairStep(props: {
  icon: React.ReactNode;
  when: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <li className="step-item">
      <span className="step-icon">{props.icon}</span>
      <span className="step-text">
        <strong>{props.when}</strong>
        <span className="muted small">{props.children}</span>
      </span>
    </li>
  );
}

/** The row that opens the raw values of the fairness check. */
function ValuesRow(props: { children: React.ReactNode }): React.JSX.Element {
  return (
    <details className="row-disclosure fair-values">
      <summary>
        Show the values and check it yourself
        <span className="row-meta">
          <CaretRight size={16} aria-hidden="true" className="row-chevron" />
        </span>
      </summary>
      <div className="row-body">{props.children}</div>
    </details>
  );
}

function Fairness(props: { view: RevealView }): React.JSX.Element {
  const { view } = props;
  return (
    <details className="card disclosure">
      <summary>Check that this day was fair</summary>
      <div className="disclosure-body">
        <ol className="step-list">
          <FairStep
            icon={<Lock size={16} aria-hidden="true" />}
            when="When the day opened"
          >
            The server published a fingerprint of the hidden photo.
          </FairStep>
          <FairStep
            icon={<PencilSimpleLine size={16} aria-hidden="true" />}
            when="While you played"
          >
            The photo stayed hidden. Its fingerprint was already public, so the
            photo couldn't be swapped after the sketches came in.
          </FairStep>
          <FairStep
            icon={<Shuffle size={16} aria-hidden="true" />}
            when="After the reveal"
          >
            Anyone can recompute the fingerprint from the photo's id and the
            secret, and see that it matches.
          </FairStep>
        </ol>
        <ValuesRow>
          <div className="stack-sm">
            <span className="label">Fingerprint published at the start</span>
            <code style={MONO}>{view.commitment}</code>
          </div>
          <div className="stack-sm">
            <span className="label">Photo id</span>
            <code style={MONO}>{view.target_id}</code>
          </div>
          <div className="stack-sm">
            <span className="label">Secret</span>
            <code style={MONO}>{view.secret}</code>
          </div>
          <div className="stack-sm">
            <span className="label">Check it yourself</span>
            <code style={MONO}>
              printf '%s:%s' {view.target_id} {view.secret} | sha256sum
            </code>
          </div>
        </ValuesRow>
      </div>
    </details>
  );
}

/** The fields a reader's check reads (spec VP1 §3.5), as one file. */
function checkFile(view: RevealView): string {
  return `${JSON.stringify(
    {
      day: view.day,
      protocol: view.protocol,
      target_id: view.target_id,
      beacon_chain: view.beacon_chain,
      beacon_round: view.beacon_round,
      round_time: view.round_time,
      beacon_signature: view.beacon_signature,
      randomness: view.randomness,
      target_index: view.target_index,
      target_salt: view.target_salt,
      target_proof: view.target_proof,
      pool_count: view.pool_count,
      pool_root: view.pool_root,
    },
    null,
    2,
  )}\n`;
}

function saveCheckFile(view: RevealView): void {
  const blob = new Blob([checkFile(view)], { type: "application/json" });
  const address = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = address;
  anchor.download = "reveal.json";
  anchor.click();
  URL.revokeObjectURL(address);
}

/**
 * The fairness check of a vp1 day (spec VP1 §3.5): the pulse that
 * picked the photo, its position in the committed set, and the command
 * that rechecks it from a saved file.
 */
function PulseFairness(props: { view: RevealView }): React.JSX.Element {
  const { view } = props;
  const publicBeacon = view.beacon_chain === "drand-quicknet";
  const pulseAddress = `https://api.drand.sh/${view.beacon_chain_hash}/public/${view.beacon_round}`;
  return (
    <details className="card disclosure">
      <summary>Check that this day was fair</summary>
      <div className="disclosure-body">
        <ol className="step-list">
          <FairStep
            icon={<Lock size={16} aria-hidden="true" />}
            when="Before the day opened"
          >
            The set of {view.pool_count} photos was fixed and its fingerprint
            published, so the set couldn't be changed to suit the pick.
          </FairStep>
          <FairStep
            icon={<PencilSimpleLine size={16} aria-hidden="true" />}
            when="While you played"
          >
            No photo was chosen while this day was open, so nobody, us included,
            could know it.
          </FairStep>
          <FairStep
            icon={<Shuffle size={16} aria-hidden="true" />}
            when="A minute after the close"
          >
            Pulse {view.beacon_round} of the drand public randomness beacon
            picked the photo from the set.
          </FairStep>
        </ol>
        <p className="notice" role="note">
          drand is a public randomness service that a group of independent
          organizations runs together. No single one of them can predict or
          change its numbers.
        </p>
        {publicBeacon ? null : (
          <div className="notice notice-warn" role="note">
            This day used a test beacon, not the public one, so its pick proves
            nothing.
          </div>
        )}
        <div className="row">
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => saveCheckFile(view)}
          >
            <DownloadSimple size={18} aria-hidden="true" />
            Save the check file
          </button>
        </div>
        <ValuesRow>
          <div className="stack-sm">
            <span className="label">Beacon pulse</span>
            <code style={MONO}>
              {publicBeacon ? (
                <a href={pulseAddress} target="_blank" rel="noreferrer">
                  {view.beacon_round}
                </a>
              ) : (
                view.beacon_round
              )}{" "}
              at {view.round_time}
            </code>
          </div>
          <div className="stack-sm">
            <span className="label">Randomness from that pulse</span>
            <code style={MONO}>{view.randomness}</code>
          </div>
          <div className="stack-sm">
            <span className="label">Photo id and its place in the set</span>
            <code style={MONO}>
              {view.target_id}, position {view.target_index} (from 0) of{" "}
              {view.pool_count}
            </code>
          </div>
          <div className="stack-sm">
            <span className="label">Fingerprint of the set</span>
            <code style={MONO}>{view.pool_root}</code>
          </div>
          <div className="stack-sm">
            <span className="label">Check it yourself</span>
            <code style={MONO}>{view.check}</code>
          </div>
        </ValuesRow>
      </div>
    </details>
  );
}
