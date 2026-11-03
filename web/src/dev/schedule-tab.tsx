/**
 * The Automatic days tab (spec BR1 §7.2): the rollover hour, what the
 * next timer run will do, what is due now, the pause, and the recent
 * runs from the timer, the command line, and this console.
 *
 * The timer itself lives in systemd, which the server cannot see. The
 * tab shows the hour the server is configured with and the run records
 * the rollover leaves in the store — a timer that stopped firing shows
 * up as a gap in the runs.
 */

import { useCallback, useEffect, useState } from "react";

import { localTimeOfUtc } from "../ui/format";
import type { DevApi } from "./api";
import {
  ConfirmAction,
  ErrorNote,
  messageOf,
  refusedRead,
  StatusBadge,
  WorkingNote,
} from "./controls";
import { relative, utcStamp } from "./format";
import type {
  DevPlan,
  DevRolloverStep,
  DevRun,
  DevRunSource,
  DevSchedule,
} from "./types";

const SOURCE_LABEL: Record<DevRunSource, string> = {
  timer: "Timer",
  "command-line": "Command line",
  console: "Console",
};

/** One step in words: "Close 2026-09-24 and score it". */
export function stepText(
  step: DevRolloverStep,
  latestDay: string | null,
  opens: string | null,
): string {
  switch (step) {
    case "close":
      return `Close ${latestDay ?? "the day"} and score it`;
    case "reveal":
      return `Reveal ${latestDay ?? "the day"}`;
    case "open":
      return `Open ${opens ?? "the next day"}`;
  }
}

function PlanSteps(props: {
  plan: DevPlan;
  latestDay: string | null;
  empty: string;
}): React.JSX.Element {
  if (props.plan.steps.length === 0) {
    return <p className="muted small">{props.empty}</p>;
  }
  return (
    <ol className="dev-steps">
      {props.plan.steps.map((step) => (
        <li key={step}>{stepText(step, props.latestDay, props.plan.opens)}</li>
      ))}
    </ol>
  );
}

/** Ticks every 30 s so the "in 3 h" distances stay true. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

export function ScheduleTab(props: {
  api: DevApi;
  reload: number;
  onChanged: () => void;
}): React.JSX.Element {
  const { api, reload, onChanged } = props;
  const now = useNow();
  const [view, setView] = useState<DevSchedule | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [actionNote, setActionNote] = useState("");
  const [lastRun, setLastRun] = useState<DevRun | null>(null);
  const [pauseNote, setPauseNote] = useState("");

  const load = useCallback(async () => {
    try {
      setView(await api.getSchedule());
      setNote("");
    } catch (error) {
      setNote(refusedRead(error));
    }
  }, [api]);

  useEffect(() => {
    void reload;
    void load();
  }, [load, reload]);

  const setPause = async (paused: boolean) => {
    setBusy(true);
    setActionNote("");
    try {
      setView(await api.setPause(paused, paused ? pauseNote.trim() : ""));
      setPauseNote("");
    } catch (error) {
      setActionNote(messageOf(error));
    } finally {
      setBusy(false);
    }
  };

  const runNow = async () => {
    setRunning(true);
    setActionNote("");
    setLastRun(null);
    try {
      const answer = await api.runRollover();
      setView(answer.schedule);
      setLastRun(answer.run);
      // A failed step comes back as a run record, not an HTTP error.
      setActionNote(
        answer.run.outcome === "failed"
          ? "The run stopped at a step that did not complete — its lines are below."
          : "",
      );
      onChanged();
    } catch (error) {
      setActionNote(messageOf(error));
      void load();
    } finally {
      setRunning(false);
    }
  };

  if (view === null) {
    return (
      <p className="muted small" role="status">
        {note === "" ? "loading…" : note}
      </p>
    );
  }

  const latestDay = view.latest?.day ?? null;
  const hour = view.closes_at_utc;

  return (
    <div className="dev-stack">
      {hour === null || view.next_run === null || view.due_now === null ? (
        <section className="card" aria-label="Automatic days">
          <div className="dev-row">
            <span className="dev-dot dev-dot-off" aria-hidden="true" />
            <h2 className="dev-h2">Automatic days are off</h2>
          </div>
          <p>
            This server has no rollover hour: <code>closes_at_utc</code> is not
            in its config. Days move only with the Days tab controls.
          </p>
          <p className="muted small">
            To turn them on, set <code>closes_at_utc</code> in the server config
            and install the day timer — see <code>deploy/README.md</code>.
          </p>
        </section>
      ) : (
        <>
          <section
            className={`card ${view.paused ? "dev-card-warn" : ""}`}
            aria-label="Automatic days"
          >
            <div className="dev-row dev-wrap">
              <span
                className={`dev-dot ${view.paused ? "dev-dot-warn" : "dev-dot-on"}`}
                aria-hidden="true"
              />
              <h2 className="dev-h2">
                {view.paused
                  ? "Automatic days are paused"
                  : "Automatic days are on"}
              </h2>
            </div>
            <p>
              Days close at <strong>{hour} UTC</strong> ({localTimeOfUtc(hour)}{" "}
              your time). The timer runs at that hour each day.
            </p>
            {view.paused ? (
              <p>
                Paused {utcStamp(view.pause_changed_at)}
                {view.pause_note === "" ? "" : ` — “${view.pause_note}”`}. The
                timer still starts, records a paused run, and moves nothing.
              </p>
            ) : null}
            <div className="dev-row dev-wrap">
              {view.paused ? (
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy}
                  onClick={() => void setPause(false)}
                >
                  Resume automatic days
                </button>
              ) : (
                <>
                  <input
                    className="input"
                    aria-label="pause note"
                    placeholder="why (optional)"
                    maxLength={200}
                    style={{ width: 260 }}
                    value={pauseNote}
                    onChange={(event) => setPauseNote(event.target.value)}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary"
                    disabled={busy}
                    onClick={() => void setPause(true)}
                  >
                    Pause automatic days
                  </button>
                </>
              )}
            </div>
          </section>

          <div className="dev-grid-2">
            <section className="card" aria-label="Next run">
              <span className="eyebrow">Next timer run</span>
              <p className="dev-big">{utcStamp(view.next_run.at)}</p>
              <p className="muted small">{relative(view.next_run.at, now)}</p>
              {view.paused ? (
                <p className="muted small">Paused: it will move nothing.</p>
              ) : (
                <PlanSteps
                  plan={view.next_run}
                  latestDay={latestDay}
                  empty={`Nothing: ${latestDay ?? "the latest day"} is not due until ${utcStamp(view.latest?.closes_at)}.`}
                />
              )}
            </section>

            <section className="card" aria-label="Due now">
              <span className="eyebrow">Due now</span>
              <div className="dev-row">
                <span>Latest day</span>
                {view.latest === null ? (
                  <span className="muted small">none yet</span>
                ) : (
                  <>
                    <strong>{view.latest.day}</strong>
                    <StatusBadge status={view.latest.status} />
                  </>
                )}
              </div>
              <PlanSteps
                plan={view.due_now}
                latestDay={latestDay}
                empty="Nothing is due now."
              />
              <div className="dev-controls">
                <ConfirmAction
                  label="Do what is due now"
                  question={`${view.due_now.steps
                    .map((step) =>
                      stepText(step, latestDay, view.due_now?.opens ?? null),
                    )
                    .join(", then ")} — now?`}
                  confirmLabel="Yes, do it now"
                  disabled={
                    busy ||
                    running ||
                    view.lock_held ||
                    view.due_now.steps.length === 0
                  }
                  onConfirm={() => void runNow()}
                />
                {running ? (
                  <WorkingNote text="Working through the due steps… a close with the live model can take a minute." />
                ) : (
                  <p className="subtle small">
                    {view.lock_held
                      ? "A rollover is running now — wait for it to end."
                      : "Does what the timer would do at this moment. The pause does not stop it."}
                  </p>
                )}
              </div>
            </section>
          </div>
        </>
      )}

      <ErrorNote text={actionNote} />
      {lastRun === null ? null : (
        <section className="card" aria-label="This run">
          <span className="eyebrow">This run · {lastRun.outcome}</span>
          <pre className="dev-pre">{lastRun.detail || "(no lines)"}</pre>
        </section>
      )}

      <section className="card" aria-label="Recent runs">
        <div className="dev-row">
          <span className="eyebrow">Recent runs</span>
          <span style={{ flex: 1 }} />
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => void load()}
          >
            Refresh
          </button>
        </div>
        {view.runs.length === 0 ? (
          <p className="muted small">
            No run yet. The timer, <code>python -m service.rollover</code>, and
            this console each leave a record here.
          </p>
        ) : (
          <table className="table dev-table">
            <thead>
              <tr>
                <th>started</th>
                <th>from</th>
                <th>outcome</th>
                <th>steps</th>
                <th>lines</th>
              </tr>
            </thead>
            <tbody>
              {view.runs.map((run) => (
                <tr key={`${run.started_at}-${run.source}`}>
                  <td>
                    {utcStamp(run.started_at)}
                    <div className="muted small">
                      {relative(run.started_at, now)}
                    </div>
                  </td>
                  <td>{SOURCE_LABEL[run.source]}</td>
                  <td>
                    <span
                      className={`dev-outcome dev-outcome-${run.outcome.replace(" ", "-")}`}
                    >
                      {run.outcome}
                    </span>
                  </td>
                  <td>{run.steps.length === 0 ? "—" : run.steps.join(", ")}</td>
                  <td>
                    <details>
                      <summary>show</summary>
                      <pre className="dev-pre">
                        {run.detail || "(no lines)"}
                      </pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="subtle small">
          The timer is <code>starvector-day.timer</code> in systemd; its hour
          must equal <code>closes_at_utc</code>. On the box,{" "}
          <code>systemctl list-timers starvector-day.timer</code> shows its next
          start. The server clock read {utcStamp(view.now)} at the last refresh.
        </p>
      </section>
    </div>
  );
}
