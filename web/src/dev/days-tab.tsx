/**
 * The Days tab (spec S2 §5, grown by spec BR1 §7.1 and §7.6): the day
 * browser, the day record with its times, the blind-run target toggle,
 * each player's send, and the stored-submission and rankings views for
 * the send the operator picks.
 *
 * The controls move the latest day — open, close, reveal — and a day
 * left behind a newer one (a closed day no reveal reached) gets its
 * own close or reveal. Each move shows that it is working, then either
 * what it did or the server's refusal in a red box.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { DevApi } from "./api";
import { DevApiError } from "./api";
import {
  ConfirmAction,
  ErrorNote,
  messageOf,
  refusedRead,
  SHOWS_TARGET,
  StatusBadge,
  WorkingNote,
} from "./controls";
import { utcShort, utcStamp } from "./format";
import { RankingsView } from "./rankings";
import { SubmissionView } from "./submission-view";
import type {
  DevDayDetail,
  DevDayRow,
  DevRankings,
  DevStored,
  LifecycleAck,
} from "./types";

export { refusedRead } from "./controls";

type Move = "open" | "close" | "reveal";

/** The line a move shows while it runs. */
function workingText(move: Move, day: string | null): string {
  switch (move) {
    case "open":
      return "Opening the next day…";
    case "close":
      return `Closing ${day ?? "the day"} and scoring each send… with the live model this can take a minute.`;
    case "reveal":
      return `Revealing ${day ?? "the day"}…`;
  }
}

/** The line a move shows when it lands. */
function doneText(move: Move, day: string | null, ack: LifecycleAck): string {
  switch (move) {
    case "open":
      return `Opened ${String(ack.day ?? "the next day")} — code ${String(ack.trial_code ?? "")}.`;
    case "close": {
      const rows = Number(ack.trial_rows ?? 0);
      return `Closed ${day ?? "the day"}: ${rows} ${rows === 1 ? "send" : "sends"} scored.`;
    }
    case "reveal":
      return `Revealed ${String(ack.day ?? day ?? "the day")}. Players can see the photo and their results.`;
  }
}

/** The refusal, with the one repair the console can name. */
function refusalText(error: unknown): string {
  const text = messageOf(error);
  return text.includes("OPENROUTER_API_KEY")
    ? `${text} Start the server that this console talks to with the key in its environment: on the box, starvector-dev reads it from /etc/starvector/env; on your own machine, set it in the shell that starts the server.`
    : text;
}

export function DaysTab(props: {
  api: DevApi;
  /** Bumped when the token changes or a move lands elsewhere. */
  reload: number;
  /** Tells the console a day moved, so each tab reads again. */
  onChanged: () => void;
}): React.JSX.Element {
  const { api, reload, onChanged } = props;
  const [days, setDays] = useState<DevDayRow[] | null>(null);
  const [note, setNote] = useState("");
  const [selected, setSelected] = useState<DevDayRow | null>(null);
  const [detail, setDetail] = useState<DevDayDetail | null>(null);
  const [sender, setSender] = useState<string | null>(null);
  const [targetShown, setTargetShown] = useState(false);
  const [stored, setStored] = useState<DevStored | null>(null);
  const [rankings, setRankings] = useState<DevRankings | null>(null);
  const [rankNote, setRankNote] = useState("");
  const [dayNote, setDayNote] = useState("");
  const [working, setWorking] = useState<Move | null>(null);
  const [moveError, setMoveError] = useState("");
  const [moveDone, setMoveDone] = useState("");
  // Each switch takes the next token; a response whose token is
  // stale belongs to a day or send the operator left and is dropped.
  const switchToken = useRef(0);
  // The day to show after the next reload: a move of an earlier day
  // stays on it, a move of the latest day shows the new latest.
  const preferred = useRef<string | null>(null);
  // Each listing takes the next token: a move and a token change can
  // start two reloads, and the older answer must not land last.
  const listToken = useRef(0);

  const showSend = useCallback(
    async (row: DevDayRow, player: string) => {
      switchToken.current += 1;
      const token = switchToken.current;
      const fresh = () => token === switchToken.current;
      setSender(player);
      setStored(null);
      setRankings(null);
      setRankNote("");
      setDayNote("");
      try {
        const document = await api.getSubmission(row.day, player);
        if (!fresh()) {
          return;
        }
        setStored(document);
        if (row.status !== "open") {
          setRankNote("scoring…");
          const board = await api.getRankings(row.day, player);
          if (!fresh()) {
            return;
          }
          setRankings(board);
          setRankNote("");
        }
      } catch (error) {
        if (!fresh()) {
          return;
        }
        if (error instanceof DevApiError && error.status === 404) {
          setDayNote("nothing sent this day");
          return;
        }
        setDayNote(messageOf(error));
        setRankNote("");
      }
    },
    [api],
  );

  const showDay = useCallback(
    async (row: DevDayRow) => {
      // A day switch clears the target and the loaded data, so
      // switching days never leaks the new target.
      switchToken.current += 1;
      const token = switchToken.current;
      setSelected(row);
      setDetail(null);
      setSender(null);
      setTargetShown(false);
      setStored(null);
      setRankings(null);
      setRankNote("");
      setDayNote("");
      try {
        const found = await api.getDay(row.day);
        if (token !== switchToken.current) {
          return;
        }
        setDetail(found);
        const first = found.sends[0];
        if (first === undefined) {
          // The Sends card says so; nothing loads below it.
          return;
        }
        await showSend(row, first.player);
      } catch (error) {
        if (token === switchToken.current) {
          setDayNote(messageOf(error));
        }
      }
    },
    [api, showSend],
  );

  const loadDays = useCallback(async () => {
    listToken.current += 1;
    const mine = listToken.current;
    try {
      const listing = await api.getDays();
      if (mine !== listToken.current) {
        return;
      }
      setDays(listing.days);
      setNote(listing.days.length === 0 ? "no day yet" : "");
      const wanted = preferred.current;
      preferred.current = null;
      const pick =
        listing.days.find((row) => row.day === wanted) ?? listing.days[0];
      if (pick !== undefined) {
        await showDay(pick);
      } else {
        setSelected(null);
      }
    } catch (error) {
      if (mine !== listToken.current) {
        return;
      }
      // No listing, no control: an open offered here would act on a
      // store the console cannot see.
      setDays(null);
      setSelected(null);
      setNote(refusedRead(error));
    }
  }, [api, showDay]);

  useEffect(() => {
    // `reload` re-fires this effect; the fetch itself does not read it.
    void reload;
    void loadDays();
  }, [loadDays, reload]);

  const move = async (
    kind: Move,
    day: string | null,
    action: () => Promise<LifecycleAck>,
    stayOn: string | null,
  ) => {
    setWorking(kind);
    setMoveError("");
    setMoveDone("");
    try {
      const ack = await action();
      setMoveDone(doneText(kind, day, ack));
      preferred.current = stayOn;
      onChanged();
    } catch (error) {
      setMoveError(refusalText(error));
    } finally {
      setWorking(null);
    }
  };

  const latestDay = days?.[0]?.day ?? null;
  // Before the listing lands there is no latest day to move, thus
  // no control is offered.
  const isLatest =
    days !== null && (selected === null || selected.day === latestDay);
  const status = selected?.status ?? "none";
  const busy = working !== null;

  const loadPreview = async () => {
    if (selected === null || sender === null) {
      return;
    }
    const token = switchToken.current;
    setRankNote("scoring…");
    try {
      const board = await api.getRankings(selected.day, sender);
      if (token === switchToken.current) {
        setRankings(board);
        setRankNote("");
      }
    } catch (error) {
      if (token === switchToken.current) {
        setRankNote(messageOf(error));
      }
    }
  };

  const controls = (): React.JSX.Element | null => {
    if (days === null) {
      return null;
    }
    const day = selected?.day ?? null;
    if (isLatest) {
      switch (status) {
        case "none":
        case "revealed":
          // The server opens a day after a reveal alone (spec BR1 §3).
          return (
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={() =>
                void move("open", null, () => api.postOpen(), null)
              }
            >
              Open the next day
            </button>
          );
        case "open":
          return (
            <ConfirmAction
              label="Close the day (scores now)"
              question={`Close ${day}? New sends stop, and each send is scored now.`}
              confirmLabel="Yes, close and score"
              disabled={busy}
              onConfirm={() =>
                void move("close", day, () => api.postClose(), null)
              }
            />
          );
        case "closing":
          return (
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy}
              onClick={() =>
                void move("close", day, () => api.postClose(), null)
              }
            >
              Finish closing (a close stopped part way)
            </button>
          );
        case "closed":
          return (
            <ConfirmAction
              label="Reveal"
              question={`Reveal ${day}? Players see the photo and their results.`}
              confirmLabel="Yes, reveal"
              disabled={busy}
              onConfirm={() =>
                void move("reveal", day, () => api.postReveal(), null)
              }
            />
          );
      }
    }
    if (day === null) {
      return null;
    }
    // A day behind the latest one (spec BR1 §7.6).
    if (status === "closed") {
      return (
        <ConfirmAction
          label="Reveal this day"
          question={`${day} stayed closed behind a newer day. Reveal it? Players see its photo and results.`}
          confirmLabel="Yes, reveal"
          disabled={busy}
          onConfirm={() =>
            void move("reveal", day, () => api.revealDay(day), day)
          }
        />
      );
    }
    if (status === "open" || status === "closing") {
      return (
        <ConfirmAction
          label="Close this day"
          question={`${day} is still ${status} behind a newer day. Close it and score its sends?`}
          confirmLabel="Yes, close and score"
          disabled={busy}
          onConfirm={() =>
            void move("close", day, () => api.closeDay(day), day)
          }
        />
      );
    }
    return null;
  };

  return (
    <div className="dev-stack">
      <div className="dev-toolbar">
        {days !== null && days.length > 0 ? (
          <select
            className="input dev-select"
            aria-label="stored day"
            value={selected?.day ?? ""}
            onChange={(event) => {
              const row = days.find((r) => r.day === event.target.value);
              if (row !== undefined) {
                setMoveDone("");
                setMoveError("");
                void showDay(row);
              }
            }}
          >
            {days.map((row) => (
              <option key={row.day} value={row.day}>
                {row.day} · {row.trial_code} · {row.status} ·{" "}
                {row.sends === 1 ? "1 send" : `${row.sends} sends`}
              </option>
            ))}
          </select>
        ) : null}
        <span className="muted small">
          {note === "" ? `status ${status}` : note}
        </span>
      </div>

      <div className="dev-grid-2">
        <section className="card" aria-label="Day">
          <div className="dev-row">
            <span className="dev-code">{selected?.trial_code ?? "······"}</span>
            {selected === null ? null : (
              <StatusBadge status={selected.status} />
            )}
          </div>
          <DayFacts selected={selected} detail={detail} />
          <div id="day-controls" className="dev-controls">
            {controls()}
            {working === null ? null : (
              <WorkingNote text={workingText(working, selected?.day ?? null)} />
            )}
            <ErrorNote text={moveError} />
            {moveDone === "" ? null : (
              <div className="notice notice-good" role="status">
                {moveDone}
              </div>
            )}
            {working === null && moveError === "" && moveDone === "" ? (
              <p className="subtle small">
                {isLatest
                  ? "The controls move the latest day."
                  : status === "revealed"
                    ? "This day is done. The controls move the latest day."
                    : "This day is behind the latest one."}
              </p>
            ) : null}
          </div>
        </section>

        <section className="card" aria-label="Sends">
          <div className="eyebrow">
            Sends{detail === null ? "" : ` · ${detail.sends.length}`}
          </div>
          {detail === null ? (
            <p className="subtle small">loading…</p>
          ) : detail.sends.length === 0 ? (
            <p className="muted">Nobody sent this day.</p>
          ) : (
            <div className="dev-scroll-x">
              <table className="table dev-table">
                <thead>
                  <tr>
                    <th>player</th>
                    <th>received (UTC)</th>
                    <th className="num">share beaten</th>
                    <th className="num">rank</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.sends.map((send) => (
                    <tr
                      key={send.player}
                      className={
                        send.player === sender ? "dev-picked" : undefined
                      }
                    >
                      <td>
                        <button
                          type="button"
                          className="dev-link-button"
                          aria-pressed={send.player === sender}
                          onClick={() => {
                            if (selected !== null) {
                              void showSend(selected, send.player);
                            }
                          }}
                        >
                          {send.display_name}
                        </button>
                        {send.display_name === send.player ? null : (
                          <span className="subtle"> {send.player}</span>
                        )}
                      </td>
                      <td>{utcShort(send.received_at)}</td>
                      <td className="num">
                        {send.trial === null
                          ? "—"
                          : `${Math.floor(send.trial.p * 100)}%`}
                      </td>
                      <td className="num">
                        {send.trial === null
                          ? "—"
                          : `${send.trial.target_rank} of ${
                              send.trial.decoy_count + 1
                            }`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {selected === null ? null : (
        <section className="card" aria-label="Target">
          <div className="dev-row dev-wrap">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setTargetShown((shown) => !shown)}
            >
              {targetShown ? "Hide the target" : "Show the target"}
            </button>
            <span className="subtle small">
              Hidden by default, so a blind run stays possible.
            </span>
          </div>
          {targetShown ? (
            <div className="dev-row dev-top dev-wrap">
              <img
                src={api.imageUrl(selected.target_id)}
                width={192}
                alt={`target for ${selected.day}`}
                className="dev-target"
              />
              <div className="dev-stack-sm">
                <code className="dev-mono">{selected.target_id}</code>
                {detail?.credit == null ? (
                  <span className="subtle small">No credit on file.</span>
                ) : (
                  <span className="small">
                    {detail.credit.title} —{" "}
                    <a
                      href={detail.credit.page}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {detail.credit.source}
                    </a>
                  </span>
                )}
              </div>
            </div>
          ) : null}
        </section>
      )}

      {stored === null ? (
        detail !== null && detail.sends.length === 0 ? null : (
          <p className="subtle small" role="status">
            {dayNote === "" ? "loading…" : dayNote}
          </p>
        )
      ) : (
        <>
          <SubmissionView stored={stored} />
          <div className="dev-row dev-wrap">
            {rankings === null && status === "open" ? (
              <ConfirmAction
                label="Score and rank the submission"
                question={SHOWS_TARGET}
                confirmLabel="Yes, show the target"
                variant="secondary"
                onConfirm={() => void loadPreview()}
              />
            ) : null}
            <span className="subtle small">
              {rankNote === ""
                ? "Scores the stored submission through the production " +
                  "path. Before close it is a preview; after close it " +
                  "equals the trial row."
                : rankNote}
            </span>
          </div>
          {rankings === null ? null : (
            <RankingsView rankings={rankings} api={api} />
          )}
        </>
      )}

      <details className="card disclosure">
        <summary>How a day runs</summary>
        <div className="disclosure-body">
          <ol className="dev-steps">
            <li>Open the next day — the code appears.</li>
            <li>Players send from the player app.</li>
            <li>
              Close the day — scoring runs through the live model, which needs
              the OpenRouter key in the server's environment.
            </li>
            <li>Reveal — the target and the results go public.</li>
          </ol>
          <p className="muted small">
            With a rollover hour set, the Automatic days tab does these on a
            timer.
          </p>
        </div>
      </details>
    </div>
  );
}

function DayFacts(props: {
  selected: DevDayRow | null;
  detail: DevDayDetail | null;
}): React.JSX.Element | null {
  const { selected, detail } = props;
  if (selected === null) {
    return null;
  }
  return (
    <dl className="dev-facts">
      <dt>day</dt>
      <dd>{selected.day}</dd>
      <dt>opened</dt>
      <dd>{utcStamp(detail?.opened_at)}</dd>
      <dt>closes</dt>
      <dd>
        {detail === null
          ? "—"
          : detail.closes_at === null
            ? "by hand (no rollover hour)"
            : utcStamp(detail.closes_at)}
      </dd>
      <dt>closed</dt>
      <dd>{utcStamp(detail?.closed_at)}</dd>
      <dt>revealed</dt>
      <dd>{utcStamp(detail?.revealed_at)}</dd>
      <dt>commitment</dt>
      <dd className="dev-mono dev-break">{selected.commitment}</dd>
      <dt>config</dt>
      <dd className="dev-mono">
        {detail === null ? "—" : detail.scoring_config_hash.slice(0, 16)}
      </dd>
    </dl>
  );
}
