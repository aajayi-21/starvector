/**
 * The results screen for one day (mock 1c, spec W1 B8; layout and
 * copy per spec BR1 §6). The heading states the result. The eye then
 * goes to the photo beside the sketch, which is the reason to open
 * the screen, and to the result against the 50% guessing mark. Below
 * one hairline, three columns share the width: the word matches, the
 * day's board, and the fairness check with its raw values behind a
 * row. On a phone the word matches stay open, and the board and the
 * fairness check are rows that open.
 *
 * Nothing here has a box: the photo, the sketch, and the buttons are
 * the things with an edge or a fill.
 *
 * No "good match" wording anywhere (spec M1 §9 copy rules): the
 * screen states the result against chance and grades nothing.
 */

import {
  ArrowLeft,
  CaretRight,
  DownloadSimple,
  Warning,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";

import { useApi } from "../api/client";
import type {
  HistoryView,
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
import {
  formatDay,
  formatShortDay,
  ordinal,
  percentBeaten,
} from "../ui/format";
import { useNarrow } from "../ui/narrow";
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
      <section className="card page-narrow">
        <h1>Results aren't in yet</h1>
        {isRefusal(reveal.error) ? (
          <p className="muted">
            The photo is revealed when the day closes and the results are worked
            out.
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
    );
  }
  return <RevealBody view={reveal.data} />;
}

/**
 * The code of a day and the played day before it, from the player's
 * history. The history holds the days with a result, so a day with no
 * send has neither.
 */
function placeInHistory(
  history: HistoryView | undefined,
  day: string,
): { code: string | null; older: string | null } {
  const days = history?.days ?? [];
  const at = days.findIndex((row) => row.day === day);
  if (at < 0) {
    return { code: null, older: null };
  }
  return {
    code: days[at]?.trial_code ?? null,
    older: days[at + 1]?.day ?? null,
  };
}

function RevealBody(props: { view: RevealView }): React.JSX.Element {
  const api = useApi();
  const { view } = props;
  const narrow = useNarrow();
  const leaderboard = useQuery({
    queryKey: ["leaderboard", view.day],
    queryFn: () => api.getLeaderboard(view.day),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api.getHistory(),
  });
  const submission = useQuery({
    queryKey: ["submission", view.day],
    queryFn: () => api.getSubmission(view.day),
    retry: false,
  });

  const sentCopy = readSentCopy(view.day);
  const replayRecord = submission.data?.record ?? sentCopy;
  const trial = view.trial;
  const place = placeInHistory(history.data, view.day);
  const players = leaderboard.data?.rows.length ?? 0;

  return (
    <div className="result">
      <header className="result-head">
        <div className="result-title">
          <p className="muted">
            {formatDay(view.day)}
            {place.code === null ? null : (
              <span className="code result-code">{place.code}</span>
            )}
          </p>
          <h1 className="h-display">
            {trial === null
              ? isPostClose(view.protocol)
                ? "The day's photo"
                : "The hidden photo"
              : `You beat ${percentBeaten(trial.p)}% of the photos`}
          </h1>
        </div>
        <nav className="result-nav" aria-label="Other days">
          {place.older === null ? null : (
            <Link to="/reveal" search={{ day: place.older }}>
              <ArrowLeft size={18} aria-hidden="true" />
              <span className="visually-hidden">The day before: </span>
              {formatShortDay(place.older)}
            </Link>
          )}
          <Link to="/history">All your results</Link>
        </nav>
      </header>

      <div className="result-top">
        <div className="pictures">
          <figure className="picture">
            <div className="picture-frame">
              <img
                src={api.imageUrl(view.target_id)}
                alt={
                  view.credit?.title ??
                  `${isPostClose(view.protocol) ? "The photo" : "Hidden target"} of ${formatDay(view.day)}`
                }
              />
            </div>
            <figcaption>
              <span className="picture-name">
                {isPostClose(view.protocol) ? "The photo" : "The hidden photo"}
              </span>
              <Credit credit={view.credit} />
            </figcaption>
          </figure>
          <figure className="picture">
            <div className="picture-frame is-sketch">
              <SketchReplay
                record={replayRecord ?? null}
                loading={submission.isPending && sentCopy === null}
                sent={trial !== null}
              />
            </div>
            <figcaption>
              <span className="picture-name">Your sketch</span>
            </figcaption>
          </figure>
        </div>
        <section className="result-summary" aria-label="Your result">
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

      <div className="result-more">
        {view.report.length === 0 ? (
          <section className="card result-words">
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
        <Fold
          title="Everyone this day"
          id="day-board"
          narrow={narrow}
          meta={
            players === 0
              ? null
              : `${players} ${players === 1 ? "player" : "players"}`
          }
        >
          <DayBoard
            view={leaderboard.data}
            pending={leaderboard.isPending}
            self={me.data?.player ?? ""}
          />
        </Fold>
        <Fold
          title="Check that this day was fair"
          id="day-fair"
          narrow={narrow}
        >
          {isPostClose(view.protocol) ? (
            <PulseFairness view={view} />
          ) : (
            <Fairness view={view} />
          )}
        </Fold>
      </div>
    </div>
  );
}

/**
 * A part of the lower row. On a wide screen it is a column with its
 * heading. On a phone it is a row that opens, so the photo, the result,
 * and the word matches stay near the top of the page.
 */
function Fold(props: {
  title: string;
  id: string;
  narrow: boolean;
  /** A short fact at the right of the closed row. */
  meta?: string | null;
  children: React.ReactNode;
}): React.JSX.Element {
  if (!props.narrow) {
    return (
      <section className="card" aria-labelledby={props.id}>
        <h2 id={props.id}>{props.title}</h2>
        {props.children}
      </section>
    );
  }
  return (
    <details className="row-disclosure result-fold">
      <summary>
        <h2 id={props.id}>{props.title}</h2>
        <span className="row-meta">
          {props.meta}
          <CaretRight size={16} aria-hidden="true" className="row-chevron" />
        </span>
      </summary>
      <section className="row-body" aria-labelledby={props.id}>
        {props.children}
      </section>
    </details>
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
      <p className="small picture-empty">
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
    <>
      <p className="result-lead">
        Your sketch matched {noun} better than{" "}
        <strong>
          {trial.beaten} of the other {trial.decoy_count}
        </strong>{" "}
        photos.
      </p>
      <ChanceMeter p={trial.p} />
      <p className="muted">
        {noun.charAt(0).toUpperCase() + noun.slice(1)} was your{" "}
        {ordinal(trial.target_rank)}-closest match out of {total}. Guessing
        averages 50%, and one day says little on its own —{" "}
        <Link to="/history">your results</Link> combine many days.
      </p>
      <div className="result-share">
        <ShareResultButton day={props.day} trial={trial} />
      </div>
    </>
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
      </a>
      . See the page for the author and license.
    </span>
  );
}

/**
 * The words that connected. A matched word's line is its matched mass
 * times the similarity of the pairing — how much it counted and how
 * close the pair was. A word with no match holds its mass in the
 * reserve bin (core/types.py MatchRow): it counted for nothing, so it
 * gets no line and comes last.
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
    <section className="card result-words" aria-labelledby="words-matched">
      <h2 id="words-matched">What connected</h2>
      <p className="muted small">
        Each word you wrote is paired with the closest detail listed for the
        photo. A longer line means a closer pairing that counted for more. Your
        drawing's overall shape is compared too; that part isn't broken down
        here.
      </p>
      <div className="word-heads" aria-hidden="true">
        <span>You wrote</span>
        <span>Closest detail in the photo</span>
      </div>
      <ul className="word-list">
        {matched.map((row) => {
          const share = Math.round((strength(row) / most) * 100);
          return (
            <li key={row.atom_id} className="word-row">
              <span className="word-pair">
                <span>{row.atom_text}</span>
                <span className="visually-hidden"> is closest to </span>
                <span className="word-detail">{row.element}</span>
              </span>
              <div
                className="meter word-meter"
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
          <li key={row.atom_id} className="word-row">
            <span className="word-pair">
              <span>{row.atom_text}</span>{" "}
              <span className="word-detail subtle">
                no close match in this photo
              </span>
            </span>
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
    <>
      {pending ? (
        <p className="subtle">Loading…</p>
      ) : view === undefined || view.rows.length === 0 ? (
        <p className="muted">No other results this day.</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Player</th>
                <th scope="col" className="num">
                  Result
                </th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr
                  key={row.player}
                  className={row.player === self ? "is-you" : undefined}
                >
                  <td>
                    <span className="board-player">
                      <AvatarCircle
                        player={row.player}
                        avatarHash={row.avatar_hash}
                        size={28}
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
      <Link to="/leaderboard">Open the leaderboard</Link>
    </>
  );
}

/** One step of the fairness check: its number, a moment, and what held. */
function FairStep(props: {
  when: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <li>
      <strong>{props.when}</strong>
      <span className="muted small">{props.children}</span>
    </li>
  );
}

/** One raw value of the fairness check, under its name. */
function RawValue(props: {
  label: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="raw-value">
      <span className="label">{props.label}</span>
      <code>{props.children}</code>
    </div>
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
    <>
      <ol className="fair-steps">
        <FairStep when="When the day opened">
          The server published a fingerprint of the hidden photo.
        </FairStep>
        <FairStep when="While you played">
          The photo stayed hidden. Its fingerprint was already public, so the
          photo couldn't be swapped after the sketches came in.
        </FairStep>
        <FairStep when="After the reveal">
          Anyone can recompute the fingerprint from the photo's id and the
          secret, and see that it matches.
        </FairStep>
      </ol>
      <ValuesRow>
        <RawValue label="Fingerprint published at the start">
          {view.commitment}
        </RawValue>
        <RawValue label="Photo id">{view.target_id}</RawValue>
        <RawValue label="Secret">{view.secret}</RawValue>
        <RawValue label="Check it yourself">
          printf '%s:%s' {view.target_id} {view.secret} | sha256sum
        </RawValue>
      </ValuesRow>
    </>
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
    <>
      <ol className="fair-steps">
        <FairStep when="Before the day opened">
          The set of {view.pool_count} photos was fixed and its fingerprint
          published, so the set couldn't be changed to suit the pick.
        </FairStep>
        <FairStep when="While you played">
          No photo was chosen while this day was open, so nobody, us included,
          could know it.
        </FairStep>
        <FairStep when="A minute after the close">
          Pulse {view.beacon_round} of the drand public randomness beacon picked
          the photo from the set.
        </FairStep>
      </ol>
      <p className="muted small" role="note">
        drand is a public randomness service that a group of independent
        organizations runs together. No single one of them can predict or change
        its numbers.
      </p>
      {publicBeacon ? null : (
        <div className="notice notice-warn" role="note">
          <Warning size={18} aria-hidden="true" />
          <span>
            This day used a test beacon, not the public one, so its pick proves
            nothing.
          </span>
        </div>
      )}
      <ValuesRow>
        <RawValue label="Beacon pulse">
          {publicBeacon ? (
            <a href={pulseAddress} target="_blank" rel="noreferrer">
              {view.beacon_round}
            </a>
          ) : (
            view.beacon_round
          )}{" "}
          at {view.round_time}
        </RawValue>
        <RawValue label="Randomness from that pulse">
          {view.randomness}
        </RawValue>
        <RawValue label="Photo id and its place in the set">
          {view.target_id}, position {view.target_index} (from 0) of{" "}
          {view.pool_count}
        </RawValue>
        <RawValue label="Fingerprint of the set">{view.pool_root}</RawValue>
        <RawValue label="Check it yourself">{view.check}</RawValue>
      </ValuesRow>
      <div>
        <button
          type="button"
          className="text-button fair-save"
          onClick={() => saveCheckFile(view)}
        >
          <DownloadSimple size={18} aria-hidden="true" />
          Save the check file
        </button>
      </div>
    </>
  );
}
