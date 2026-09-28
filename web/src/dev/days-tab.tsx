/**
 * The Days tab (spec S2 §5, grown by spec BR1 §7.1): the day browser
 * with the latest-day-only control rule, the day record with its
 * times, the blind-run target toggle, each player's send, and the
 * stored-submission and rankings views for the send the operator
 * picks.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { DevApi } from "./api";
import { DevApiError } from "./api";
import { utcStamp } from "./format";
import { RankingsView } from "./rankings";
import { SubmissionView } from "./submission-view";
import type { DevDayDetail, DevDayRow, DevRankings, DevStored } from "./types";

function messageOf(error: unknown): string {
  return error instanceof DevApiError ? error.message : "refused";
}

/** The wording rule for a refused dev read: see DevApp. */
export function refusedRead(error: unknown): string {
  return error instanceof DevApiError && error.status === 404
    ? "not found: start the server with --dev, or the operator " +
        "token is missing or wrong"
    : messageOf(error);
}

export function StatusTag(props: { status: string }): React.JSX.Element {
  return (
    <span className={`dev-status dev-status-${props.status}`}>
      {props.status}
    </span>
  );
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
  const [controlNote, setControlNote] = useState("");
  // Each switch takes the next token; a response whose token is
  // stale belongs to a day or send the operator left and is dropped.
  const switchToken = useRef(0);

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
          setDayNote("nothing sent this day");
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
    try {
      const listing = await api.getDays();
      setDays(listing.days);
      setNote(listing.days.length === 0 ? "no day yet" : "");
      const first = listing.days[0];
      if (first !== undefined) {
        await showDay(first);
      } else {
        setSelected(null);
      }
    } catch (error) {
      setDays([]);
      setSelected(null);
      // A refused operator check on a dev read answers the same 404
      // the server gives with no --dev flag, and that is deliberate:
      // a 401 there would announce that dev mode is on. The console
      // only ever runs against a dev server, thus it can say both
      // causes out loud without opening the oracle on the wire.
      setNote(refusedRead(error));
    }
  }, [api, showDay]);

  useEffect(() => {
    // `reload` re-fires this effect; the fetch itself does not read it.
    void reload;
    void loadDays();
  }, [loadDays, reload]);

  const act = async (action: () => Promise<unknown>, confirmText?: string) => {
    if (confirmText !== undefined && !window.confirm(confirmText)) {
      return;
    }
    setControlNote("working…");
    try {
      await action();
      setControlNote("");
      onChanged();
    } catch (error) {
      setControlNote(messageOf(error));
    }
  };

  const latestDay = days?.[0]?.day;
  // Before the listing lands there is no latest day to move, thus
  // no control is offered.
  const movable =
    days !== null && (selected === null || selected.day === latestDay);
  const status = selected?.status ?? "none";

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

  return (
    <div className="dev-stack">
      <div className="dev-toolbar">
        {days !== null && days.length > 0 ? (
          <select
            className="input"
            aria-label="stored day"
            style={{ width: "auto" }}
            value={selected?.day ?? ""}
            onChange={(event) => {
              const row = days.find((r) => r.day === event.target.value);
              if (row !== undefined) {
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
        <span className="dev-muted">
          {note === "" ? `status ${status}` : note}
        </span>
      </div>

      <div className="dev-grid-2">
        <section className="card dev-card" aria-label="Day">
          <div className="dev-row">
            <span className="dev-code">{selected?.trial_code ?? "······"}</span>
            {selected === null ? null : <StatusTag status={selected.status} />}
          </div>
          <DayFacts selected={selected} detail={detail} />
          <div id="day-controls" className="dev-row dev-wrap">
            {/* The server opens a day after a reveal alone (spec BR1
                §3): a closed day left behind has no way back. */}
            {movable && (status === "revealed" || status === "none") ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => act(() => api.postOpen())}
              >
                Open the next day
              </button>
            ) : null}
            {movable && status === "open" ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() =>
                  act(
                    () => api.postClose(),
                    "Close the day? Scoring runs and the window locks.",
                  )
                }
              >
                Close the day (scores now)
              </button>
            ) : null}
            {movable && status === "closing" ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => act(() => api.postClose())}
              >
                Finish closing (a close stopped part way)
              </button>
            ) : null}
            {movable && status === "closed" ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => act(() => api.postReveal())}
              >
                Reveal
              </button>
            ) : null}
            <span className="dev-hint">
              {controlNote === ""
                ? "each stored day is readable — the controls move the latest one"
                : controlNote}
            </span>
          </div>
        </section>

        <section className="card dev-card" aria-label="Sends">
          <span className="card-kicker">
            Sends{detail === null ? "" : ` · ${detail.sends.length}`}
          </span>
          {detail === null ? (
            <p className="dev-muted">loading…</p>
          ) : detail.sends.length === 0 ? (
            <p className="dev-muted">Nobody sent this day.</p>
          ) : (
            <table className="table dev-table">
              <thead>
                <tr>
                  <th>player</th>
                  <th>received</th>
                  <th className="dev-num">share beaten</th>
                  <th className="dev-num">rank</th>
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
                        className="btn btn-ghost dev-cell-button"
                        aria-pressed={send.player === sender}
                        onClick={() => {
                          if (selected !== null) {
                            void showSend(selected, send.player);
                          }
                        }}
                      >
                        {send.display_name}
                        {send.display_name === send.player ? null : (
                          <span className="dev-muted"> ({send.player})</span>
                        )}
                      </button>
                    </td>
                    <td>{utcStamp(send.received_at)}</td>
                    <td className="dev-num">
                      {send.trial === null
                        ? "—"
                        : `${Math.floor(send.trial.p * 100)}%`}
                    </td>
                    <td className="dev-num">
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
          )}
        </section>
      </div>

      {selected === null ? null : (
        <section className="card dev-card" aria-label="Target">
          <div className="dev-row">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setTargetShown((shown) => !shown)}
            >
              {targetShown ? "Hide the target" : "Show the target"}
            </button>
            <span className="dev-hint">
              hidden by default, so a blind run stays possible
            </span>
          </div>
          {targetShown ? (
            <div className="dev-row dev-top">
              <img
                src={api.imageUrl(selected.target_id)}
                width={192}
                alt={`target for ${selected.day}`}
                className="dev-target"
              />
              <div className="dev-stack-sm">
                <code className="dev-mono">{selected.target_id}</code>
                {detail?.credit == null ? (
                  <span className="dev-muted">no credit on file</span>
                ) : (
                  <span>
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
        <p className="dev-muted" role="status">
          {dayNote === "" ? "loading…" : dayNote}
        </p>
      ) : (
        <>
          <SubmissionView stored={stored} />
          <div className="dev-row">
            {rankings === null && status === "open" ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void loadPreview()}
              >
                Score and rank the submission
              </button>
            ) : null}
            <span className="dev-hint">
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

      <details className="dev-help">
        <summary>How a day runs</summary>
        <ol>
          <li>Open the next day — the code appears.</li>
          <li>Players send from the player app.</li>
          <li>Close the day — the one live step; scoring runs.</li>
          <li>Reveal — the target and the report go public.</li>
        </ol>
        <p>
          With a rollover hour set, the Automatic days tab does these on a
          timer.
        </p>
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
      <dd className="dev-mono dev-break">
        {detail === null ? "—" : detail.scoring_config_hash.slice(0, 16)}
      </dd>
    </dl>
  );
}
