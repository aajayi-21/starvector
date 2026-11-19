/**
 * The Days tab (spec S2 §5, grown by spec BR1 §7.1 and §7.6): the day
 * browser, the day's stages and numbers, the one next step, each
 * player's send with the stored-submission and rankings views for the
 * send the operator picks, and the rows that open: the blind-run
 * target toggle, the technical details of the record, and the help.
 *
 * The controls move the latest day — open, close, reveal — and a day
 * left behind a newer one (a closed day no reveal reached) gets its
 * own close or reveal. Each move shows that it is working, then either
 * what it did or the server's refusal in a red box.
 *
 * The target shows only when the operator opens its row. The row
 * closes on each day switch, and the image address is set only while
 * the row is open, thus a blind run stays possible (spec S2 §5).
 */

import { Check } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AboutView } from "../api/types";
import { formatRemaining } from "../ui/format";
import type { DevApi } from "./api";
import { DevApiError } from "./api";
import type { Access } from "./controls";
import {
  accessOfFailure,
  ConfirmAction,
  Disclosure,
  ErrorNote,
  messageOf,
  refusedRead,
  SHOWS_TARGET,
  StatusBadge,
  useNow,
  WorkingNote,
} from "./controls";
import { relative, utcDate, utcShort, utcStamp, utcTime } from "./format";
import { RankingsView } from "./rankings";
import type { DayStage } from "./stages";
import { dayProtocol, dayStages, isPicked, pickSentence } from "./stages";
import { SubmissionView } from "./submission-view";
import type {
  DevDayDetail,
  DevDayRow,
  DevRankings,
  DevSchedule,
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
      const skipped = Number(ack.quarantined ?? 0);
      const tail =
        skipped === 0
          ? ""
          : ` ${skipped} refused ${skipped === 1 ? "send was" : "sends were"} skipped (quarantined).`;
      return `Closed ${day ?? "the day"}: ${rows} ${rows === 1 ? "send" : "sends"} scored.${tail}`;
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

/** The one next step of the shown day: what it is and what it does. */
interface NextStep {
  title: string;
  text: string;
  control: React.JSX.Element | null;
}

/** What the schedule does by itself, as the last sentence of a step. */
function scheduleClause(schedule: DevSchedule | null): string {
  if (schedule === null) {
    return "";
  }
  if (schedule.closes_at_utc === null) {
    return " Days move by hand on this server.";
  }
  return schedule.paused
    ? " Automatic days are paused, so the schedule does not do this."
    : " The schedule does this by itself on its next run.";
}

export function DaysTab(props: {
  api: DevApi;
  /** Bumped when the token changes or a move lands elsewhere. */
  reload: number;
  /** Tells the console a day moved, so each tab reads again. */
  onChanged: () => void;
  /** The season facts, for the count of photos. Null until they load. */
  about?: AboutView | null;
  /** The newest schedule that the Automatic days tab read, or null. */
  schedule?: DevSchedule | null;
  /** Tells the console what each day listing says about the token. */
  onAccess?: (access: Access) => void;
}): React.JSX.Element {
  const { api, reload, onChanged, onAccess } = props;
  const about = props.about ?? null;
  const schedule = props.schedule ?? null;
  const now = useNow();
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
      setNote("");
      onAccess?.({ state: "connected" });
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
      onAccess?.(accessOfFailure(error));
    }
  }, [api, showDay, onAccess]);

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

  const day = selected?.day ?? null;
  const protocol = dayProtocol(selected?.commitment ?? null);
  const closesAt = detail?.closes_at ?? null;

  const openControl = (
    <button
      type="button"
      className="btn btn-primary"
      disabled={busy}
      onClick={() => void move("open", null, () => api.postOpen(), null)}
    >
      Open the next day
    </button>
  );

  const nextStep = (): NextStep => {
    if (isLatest) {
      switch (status) {
        case "none":
          return {
            title: "Next step: open the first day",
            text: `Starts a day with a new code. Players can send when it opens.${scheduleClause(schedule)}`,
            control: openControl,
          };
        case "revealed":
          // The server opens a day after a reveal alone (spec BR1 §3).
          return {
            title: "Next step: open the next day",
            text: `Starts a new day with a new code. Players can send when it opens.${scheduleClause(schedule)}`,
            control: openControl,
          };
        case "open": {
          // A vp1 close also picks the target, and the server refuses
          // it long before the pulse of the day (spec VP1 §5).
          const vp1 = protocol === "vp1";
          const what = vp1
            ? "stops new sends and scores everyone, and then a public random number picks the photo. It can't be reopened."
            : "stops new sends and scores everyone. It can't be reopened.";
          const control = (
            <ConfirmAction
              label="Close the day"
              question={`Close ${day}? New sends stop, and each send is scored now.`}
              confirmLabel="Yes, close and score"
              variant="danger"
              disabled={busy}
              onConfirm={() =>
                void move("close", day, () => api.postClose(), null)
              }
            />
          );
          const waits =
            schedule !== null &&
            schedule.closes_at_utc !== null &&
            !schedule.paused &&
            closesAt !== null &&
            new Date(closesAt).getTime() > now;
          if (!waits) {
            return {
              title: "Next step: close the day",
              text: `Closing ${what}${scheduleClause(schedule)}`,
              control,
            };
          }
          const itself = `The schedule closes this day by itself at ${utcStamp(closesAt)} (${relative(closesAt, now)}).`;
          return {
            title: "Nothing is due yet",
            text: vp1
              ? `${itself} The server refuses a close by hand before that time, because the random number that picks the photo comes after it. The close ${what}`
              : `${itself} Closing it by hand now ${what}`,
            control,
          };
        }
        case "closing":
          return {
            title: "Next step: finish closing",
            text: `A close stopped part way. Finishing it scores the sends that are left and closes the day. It can't be reopened.${scheduleClause(schedule)}`,
            control: (
              <button
                type="button"
                className="btn btn-danger"
                disabled={busy}
                onClick={() =>
                  void move("close", day, () => api.postClose(), null)
                }
              >
                Finish closing
              </button>
            ),
          };
        case "closed":
          return {
            title: "Next step: reveal the day",
            text: `Shows players the photo and their results. It can't be hidden again.${scheduleClause(schedule)}`,
            control: (
              <ConfirmAction
                label="Reveal"
                question={`Reveal ${day}? Players see the photo and their results.`}
                confirmLabel="Yes, reveal"
                variant="danger"
                disabled={busy}
                onConfirm={() =>
                  void move("reveal", day, () => api.postReveal(), null)
                }
              />
            ),
          };
      }
    }
    // A day behind the latest one (spec BR1 §7.6).
    if (day !== null && status === "closed") {
      return {
        title: "This day stayed closed behind a newer day",
        text: "Revealing it shows players its photo and results. It can't be hidden again.",
        control: (
          <ConfirmAction
            label="Reveal this day"
            question={`${day} stayed closed behind a newer day. Reveal it? Players see its photo and results.`}
            confirmLabel="Yes, reveal"
            variant="danger"
            disabled={busy}
            onConfirm={() =>
              void move("reveal", day, () => api.revealDay(day), day)
            }
          />
        ),
      };
    }
    if (day !== null && (status === "open" || status === "closing")) {
      return {
        title: `This day is still ${status} behind a newer day`,
        text: "Closing it stops its sends and scores them. It can't be reopened.",
        control: (
          <ConfirmAction
            label="Close this day"
            question={`${day} is still ${status} behind a newer day. Close it and score its sends?`}
            confirmLabel="Yes, close and score"
            variant="danger"
            disabled={busy}
            onConfirm={() =>
              void move("close", day, () => api.closeDay(day), day)
            }
          />
        ),
      };
    }
    return {
      title: "Nothing is due for this day",
      text: "This day is done.",
      control: null,
    };
  };

  if (days === null) {
    // No listing, no skeleton: one line while it loads, or the
    // refusal in plain words.
    return note === "" ? (
      <p className="muted small" role="status">
        Loading the days…
      </p>
    ) : (
      <ErrorNote text={note} />
    );
  }

  const step = nextStep();

  return (
    <div className="dev-stack">
      <section className="card" aria-label="Day">
        <div className="dev-day-head">
          {selected === null ? (
            <h2 className="dev-h2">No day yet</h2>
          ) : (
            <div className="dev-row dev-wrap">
              <span className="dev-code">{selected.trial_code}</span>
              <span data-testid="day-status">
                <StatusBadge status={selected.status} />
              </span>
              <span className="dev-day-label">{selected.day}</span>
              <span className={`badge ${isLatest ? "badge-accent" : ""}`}>
                {isLatest ? "Latest day" : "Earlier day"}
              </span>
            </div>
          )}
          {days.length > 0 ? (
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
                  {(row.quarantined ?? 0) > 0
                    ? ` · ${row.quarantined} quarantined`
                    : ""}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        {selected === null ? null : (
          <>
            <StageTrack
              stages={dayStages(
                protocol,
                selected.status,
                isPicked(selected.target_id),
              )}
              detail={detail}
            />
            <p className="hint">{pickSentence(protocol)}</p>
            <DayTiles
              selected={selected}
              detail={detail}
              about={about}
              schedule={schedule}
              now={now}
            />
          </>
        )}

        <div id="day-controls" className="dev-next">
          <h3 className="dev-next-title">{step.title}</h3>
          <p>{step.text}</p>
          {step.control}
          {working === null ? null : (
            <WorkingNote text={workingText(working, selected?.day ?? null)} />
          )}
          <ErrorNote text={moveError} />
          {moveDone === "" ? null : (
            <div className="notice notice-good" role="status">
              {moveDone}
            </div>
          )}
          <p className="subtle small">
            {isLatest
              ? "These controls act on the latest day."
              : "This day is behind the latest one. Pick the latest day to move it."}
          </p>
        </div>
      </section>

      {selected === null ? null : (
        <section className="card" aria-label="Sends">
          <div className="eyebrow">
            Sends{detail === null ? "" : ` · ${detail.sends.length}`}
          </div>
          {detail === null ? (
            <p className="subtle small">Loading…</p>
          ) : detail.sends.length === 0 ? (
            <p className="muted">Nobody sent this day.</p>
          ) : (
            <div className="dev-scroll-x">
              <table className="table dev-table">
                <thead>
                  <tr>
                    <th>Player</th>
                    <th>Received (UTC)</th>
                    <th className="num">Share beaten</th>
                    <th className="num">Rank</th>
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
                          onClick={() => void showSend(selected, send.player)}
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
      )}

      {selected === null ? null : stored === null ? (
        detail !== null && detail.sends.length === 0 ? null : (
          <p className="subtle small" role="status">
            {dayNote === "" ? "Loading…" : dayNote}
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

      <section className="card dev-rows" aria-label="More">
        <div className="row-list">
          {selected === null ? null : (
            <TargetRow
              api={api}
              selected={selected}
              detail={detail}
              shown={targetShown}
              onToggle={setTargetShown}
            />
          )}
          {selected === null ? null : (
            <Disclosure
              title="Technical details"
              meta="Commitment, config, times"
            >
              <DayFacts selected={selected} detail={detail} />
            </Disclosure>
          )}
          <Disclosure title="How a day runs" meta="The four moves">
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
          </Disclosure>
        </div>
      </section>
    </div>
  );
}

/** The line below a stage label: its time, or what it waits for. */
function stageNote(stage: DayStage, detail: DevDayDetail | null): string {
  if (detail === null) {
    return "—";
  }
  switch (stage.id) {
    case "opened":
      return utcStamp(detail.opened_at);
    case "close":
      if (stage.state === "done") {
        return utcStamp(detail.closed_at);
      }
      if (detail.status === "closing") {
        return "Stopped part way";
      }
      return detail.closes_at === null
        ? "By hand (no rollover hour)"
        : `Due ${utcStamp(detail.closes_at)}`;
    case "pick":
      return stage.state === "done" ? "Picked" : "After the close";
    case "reveal":
      if (stage.state === "done") {
        return utcStamp(detail.revealed_at);
      }
      return stage.state === "current" ? "Ready" : "After the close";
  }
}

const STATE_WORD: Record<DayStage["state"], string> = {
  done: "done",
  current: "next",
  pending: "later",
};

const STATE_CLASS: Record<DayStage["state"], string> = {
  done: "is-done",
  current: "dev-stage-current",
  pending: "is-pending",
};

/**
 * The stages of the day in one row: done stages have a check mark, the
 * stage that the next move completes stands out, and the stages after
 * it are muted.
 */
function StageTrack(props: {
  stages: DayStage[];
  detail: DevDayDetail | null;
}): React.JSX.Element {
  return (
    <ol className="step-list dev-track" aria-label="Day stages">
      {props.stages.map((stage, index) => (
        <li
          key={stage.id}
          className={`step-item ${STATE_CLASS[stage.state]}`}
          aria-current={stage.state === "current" ? "step" : undefined}
          data-stage={stage.id}
          data-state={stage.state}
        >
          <span className="step-icon" aria-hidden="true">
            {stage.state === "done" ? (
              <Check size={16} weight="bold" />
            ) : (
              index + 1
            )}
          </span>
          <span className="step-text">
            <strong>
              {stage.label}
              <span className="visually-hidden">
                {" "}
                ({STATE_WORD[stage.state]})
              </span>
            </strong>
            <span className="hint">{stageNote(stage, props.detail)}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** One number of the day, with its label above and a note below. */
function Tile(props: {
  label: string;
  value: string;
  note?: string;
}): React.JSX.Element {
  return (
    <div className="tile">
      <span className="tile-label">{props.label}</span>
      <span className="tile-value">{props.value}</span>
      {props.note === undefined || props.note === "" ? null : (
        <span className="dev-tile-note">{props.note}</span>
      )}
    </div>
  );
}

/** The close of the day as a tile: the time left, or the time it closed. */
function closeTile(
  detail: DevDayDetail | null,
  now: number,
): { label: string; value: string; note: string } {
  if (detail === null) {
    return { label: "Closes in", value: "—", note: "" };
  }
  if (detail.status === "closed" || detail.status === "revealed") {
    return {
      label: "Closed at",
      value: utcTime(detail.closed_at),
      note: utcDate(detail.closed_at),
    };
  }
  if (detail.status === "closing") {
    return {
      label: "Closing",
      value: "Part way",
      note: "A close stopped part way",
    };
  }
  if (detail.closes_at === null) {
    return { label: "Closes", value: "By hand", note: "No rollover hour" };
  }
  const left = new Date(detail.closes_at).getTime() - now;
  return {
    label: "Closes in",
    value: left > 0 ? formatRemaining(left) : "Due now",
    note: utcStamp(detail.closes_at),
  };
}

/** The four numbers of the day. Each is a value the console holds. */
function DayTiles(props: {
  selected: DevDayRow;
  detail: DevDayDetail | null;
  about: AboutView | null;
  schedule: DevSchedule | null;
  now: number;
}): React.JSX.Element {
  const { selected, detail, about, schedule, now } = props;
  const close = closeTile(detail, now);
  const skipped = selected.quarantined ?? 0;
  return (
    <div className="tiles dev-tiles">
      <Tile
        label="Sends"
        value={String(detail?.sends.length ?? selected.sends)}
        note={skipped > 0 ? `${skipped} quarantined` : ""}
      />
      <Tile label={close.label} value={close.value} note={close.note} />
      <Tile
        label="Photos in set"
        value={about === null ? "—" : String(about.photo_count)}
      />
      <Tile
        label="Automatic days"
        value={
          schedule === null
            ? "—"
            : schedule.closes_at_utc === null
              ? "Off"
              : schedule.paused
                ? "Paused"
                : "On"
        }
        note={
          schedule === null || schedule.closes_at_utc === null
            ? ""
            : `Close at ${schedule.closes_at_utc} UTC`
        }
      />
    </div>
  );
}

/**
 * The blind-run target toggle as a row that opens (spec S2 §5). The
 * caller holds the flag and clears it on each day switch. The image
 * element exists only while the row is open, thus the browser asks for
 * the target only when the operator asks.
 */
function TargetRow(props: {
  api: DevApi;
  selected: DevDayRow;
  detail: DevDayDetail | null;
  shown: boolean;
  onToggle: (shown: boolean) => void;
}): React.JSX.Element {
  const { api, selected, detail, shown, onToggle } = props;
  const targetId = selected.target_id;
  // A vp1 day holds no target before the close (spec VP1 §3.3), and
  // the words must not say that one is hidden (spec VP1 §8).
  const picked = isPicked(targetId);
  return (
    <Disclosure
      title={shown ? "Hide the day's photo" : "Show the day's photo"}
      meta={picked ? "Hidden so you can stay blind" : "Not picked yet"}
      open={shown}
      onToggle={onToggle}
    >
      {!shown ? null : targetId === null || !picked ? (
        <p className="muted small">
          This day has no photo yet. A public random number picks it after the
          close.
        </p>
      ) : (
        <div className="dev-row dev-top dev-wrap">
          <img
            src={api.imageUrl(targetId)}
            width={192}
            alt={`target for ${selected.day}`}
            className="dev-target"
          />
          <div className="dev-stack-sm">
            <code className="dev-mono dev-break">{targetId}</code>
            {detail?.credit == null ? (
              <span className="subtle small">No credit on file.</span>
            ) : (
              <span className="small">
                {detail.credit.title} —{" "}
                <a href={detail.credit.page} target="_blank" rel="noreferrer">
                  {detail.credit.source}
                </a>
              </span>
            )}
          </div>
        </div>
      )}
    </Disclosure>
  );
}

/** The record of the day as stored: the raw facts, one to a row. */
function DayFacts(props: {
  selected: DevDayRow;
  detail: DevDayDetail | null;
}): React.JSX.Element {
  const { selected, detail } = props;
  return (
    <dl className="dev-facts">
      <dt>Day</dt>
      <dd>{selected.day}</dd>
      <dt>Protocol</dt>
      <dd className="dev-mono">{dayProtocol(selected.commitment)}</dd>
      <dt>Opened</dt>
      <dd>{utcStamp(detail?.opened_at)}</dd>
      <dt>Closes</dt>
      <dd>
        {detail === null
          ? "—"
          : detail.closes_at === null
            ? "By hand (no rollover hour)"
            : utcStamp(detail.closes_at)}
      </dd>
      <dt>Closed</dt>
      <dd>{utcStamp(detail?.closed_at)}</dd>
      <dt>Revealed</dt>
      <dd>{utcStamp(detail?.revealed_at)}</dd>
      <dt>Commitment</dt>
      <dd className="dev-mono dev-break">
        {selected.commitment === null || selected.commitment === ""
          ? "None: a vp1 day has no commitment"
          : selected.commitment}
      </dd>
      <dt>Config</dt>
      <dd className="dev-mono">
        {detail === null ? "—" : detail.scoring_config_hash.slice(0, 16)}
      </dd>
    </dl>
  );
}
