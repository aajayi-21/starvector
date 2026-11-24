/**
 * The instant trial (spec IM1 §5 and §16): the second view of the Play
 * place, in the Studio layout that practice had. The player gets a
 * code, sketches and types, and sends. A public random number, which
 * is not there at the time of the send, picks the photo some seconds
 * after it. The screen then shows the photo and the result.
 *
 * Five conditions: before a trial (`Get a code`), sketching, waiting
 * for the pulse, the result, and at the limit of the day. An account
 * or a guest plays (spec IM1 §7). The server keeps each trial, and each
 * one is public, so the screen says that before the send.
 *
 * The sketch saves on this device with the trial as its key. It stays
 * through the wait and the result, so a reload shows it again, and it
 * goes when the player starts the next trial.
 */

import { Plus } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useApi } from "../api/client";
import type {
  InstantPending,
  InstantReceipt,
  InstantSettled,
  InstantView,
} from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { CanvasPanel } from "../intake/canvas-panel";
import {
  clearInstantDraft,
  hasContent,
  readInstantDraft,
  writeInstantDraft,
} from "../intake/drafts";
import { GroupControls } from "../intake/groups-card";
import { ImpressionsCard } from "../intake/impressions-card";
import { sendBlock, sendBlockHint } from "../intake/send-gate";
import { shareAddress, trialAddress } from "../share/address";
import { NoticeText } from "../signin/notice-text";
import type { DocHistory, Point, SketchDoc } from "../sketch/core";
import {
  addStroke,
  canRedo,
  canUndo,
  clearSketch,
  current,
  EMPTY_DOC,
  historyOf,
  makeGroup,
  pushDoc,
  redo,
  serialize,
  undo,
} from "../sketch/core";
import { ChanceMeter } from "../ui/chance-meter";
import { DayCode } from "../ui/code-cells";
import { ordinal, percentBeaten } from "../ui/format";
import { useGuestGate } from "../ui/guest-gate-context";
import { PlayFrame, PlayHow, PlayMessage, PlaySwitch } from "../ui/play-switch";
import { Credit, WordMatches } from "./reveal";

/** The pause between two reads of a trial that waits for its pulse. */
export const INSTANT_POLL_MS = 1000;

/** The trial on the screen: its address and its code. */
interface ShownTrial {
  date: string;
  trial_id: string;
  trial_code: string;
}

export function InstantScreen(): React.JSX.Element {
  return (
    <PlayFrame>
      <InstantPlace />
    </PlayFrame>
  );
}

function InstantPlace(): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const view = useQuery({
    queryKey: ["instant"],
    queryFn: () => api.getInstant(),
  });
  // The trial that the player sent on this screen, and the one that
  // the player left with `Again`.
  const [focus, setFocus] = useState<string | null>(null);
  const [left, setLeft] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: () => api.startInstant(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["instant"] }),
  });
  const agree = useMutation({
    mutationFn: () => api.makeGuest(true),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["instant"] }),
  });

  if (view.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading…
      </p>
    );
  }
  if (view.isError || view.data === undefined) {
    return (
      <PlayMessage title="Instant trial" view="instant">
        {isRefusal(view.error) ? (
          <p className="muted">Instant trials are not open on this server.</p>
        ) : (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(view.error)}
          </div>
        )}
      </PlayMessage>
    );
  }
  const data = view.data;

  // A guest agrees to a new notice version here. An account does it on
  // the notice screen of the shell (spec R1 §3).
  if (data.needs_agreement && data.kind === "guest") {
    return (
      <PlayMessage title="Before you play" view="instant">
        <NoticeText />
        <div>
          <button
            type="button"
            className="btn btn-primary"
            disabled={agree.isPending}
            onClick={() => agree.mutate()}
          >
            I agree
          </button>
        </div>
        {agree.isError ? (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(agree.error)}
          </div>
        ) : null}
      </PlayMessage>
    );
  }

  // The trial on the screen: the open one, then the one sent here,
  // then one that waits for its pulse (a reload in the wait).
  const newest = data.trials[0];
  const sent =
    data.trials.find((row) => row.trial_id === focus) ??
    (newest?.status === "pending" ? newest : undefined);
  const shown: ShownTrial | undefined =
    data.open ??
    (sent !== undefined && sent.trial_id !== left ? sent : undefined);

  if (shown !== undefined) {
    return (
      <InstantWorkspace
        key={shown.trial_id}
        trial={shown}
        view={data}
        serverSent={data.open?.trial_id !== shown.trial_id}
        onSent={() => {
          setFocus(shown.trial_id);
          void queryClient.invalidateQueries({ queryKey: ["instant"] });
        }}
        onSettled={() =>
          void queryClient.invalidateQueries({ queryKey: ["instant"] })
        }
        onAgain={() => {
          clearInstantDraft();
          setLeft(shown.trial_id);
          setFocus(null);
        }}
      />
    );
  }

  return (
    <PlayMessage title="Instant trial" view="instant">
      <p className="muted">
        Sketch and describe what comes to mind for a code. A few seconds after
        you send, a photo is picked at random, and you see it and how close you
        came.
      </p>
      {data.left_today > 0 ? (
        <>
          <p>
            <strong>{data.left_today}</strong> of {data.day_cap} left today.
            Every trial is saved and public, and none can be removed.
          </p>
          <div>
            <button
              type="button"
              className="btn btn-primary btn-large"
              disabled={start.isPending}
              onClick={() => start.mutate()}
            >
              Get a code
            </button>
          </div>
        </>
      ) : (
        <p role="status">
          That's all {data.day_cap} instant trials for today. More open at
          midnight UTC.
        </p>
      )}
      {start.isError ? (
        <div className="notice notice-bad" role="alert">
          {friendlyMessage(start.error)}
        </div>
      ) : null}
      <RecordLine view={data} />
      {data.kind === "guest" ? <GuestInvitation /> : null}
    </PlayMessage>
  );
}

/** The instant record of the owner, in one line (spec IM1 §9). */
function RecordLine(props: { view: InstantView }): React.JSX.Element | null {
  const { record } = props.view;
  if (record.sent === 0) {
    return null;
  }
  const waiting = record.sent - record.settled;
  return (
    <p className="muted small instant-record">
      Your record: {record.sent} {record.sent === 1 ? "trial" : "trials"}
      {record.mean_p === null
        ? ""
        : `, ${percentBeaten(record.mean_p)}% on average`}
      {waiting > 0 ? `, ${waiting} waiting for a photo` : ""}. Chance is 50%.
    </p>
  );
}

/** The way from guest play to an account (spec IM1 §16). */
function GuestInvitation(): React.JSX.Element | null {
  const gate = useGuestGate();
  if (gate === null) {
    return null;
  }
  return (
    <section className="instant-invite" aria-label="Make an account">
      <p className="muted">
        The daily challenge is one shared photo a day, with a leaderboard. It
        needs an account. Your instant trials come with you.
      </p>
      <div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={gate.openGate}
        >
          Make an account
        </button>
      </div>
    </section>
  );
}

function InstantWorkspace(props: {
  trial: ShownTrial;
  view: InstantView;
  /** True when the server holds the send of this trial. */
  serverSent: boolean;
  onSent: () => void;
  onSettled: () => void;
  onAgain: () => void;
}): React.JSX.Element {
  const api = useApi();
  const { trial } = props;
  const [restored] = useState(() => readInstantDraft(trial.trial_id));
  const [history, setHistory] = useState<DocHistory>(() =>
    historyOf(restored?.doc ?? EMPTY_DOC),
  );
  const [selection, setSelection] = useState<ReadonlySet<number>>(
    () => new Set<number>(),
  );
  const [mode, setMode] = useState<"draw" | "select">("draw");
  const [colorIndex, setColorIndex] = useState(0);
  const [impressions, setImpressions] = useState<string[]>(
    () => restored?.impressions ?? [],
  );
  const [typedWord, setTypedWord] = useState(() => restored?.typedWord ?? "");
  const [receipt, setReceipt] = useState<InstantReceipt | null>(null);
  const nextStrokeId = useRef(restored?.nextStrokeId ?? 1);

  const doc = current(history);
  const commit = (next: SketchDoc) => setHistory((h) => pushDoc(h, next));
  const sent = props.serverSent || receipt !== null;

  // The same in-flight ref lock as the daily send: isPending flips a
  // task late, and one trial has one send.
  const sendingRef = useRef(false);
  const send = useMutation({
    mutationFn: (words: string[]) =>
      api.sendInstant(trial.date, trial.trial_id, serialize(doc, words, "")),
    onSuccess: (answer) => {
      setReceipt(answer);
      props.onSent();
    },
    onSettled: () => {
      sendingRef.current = false;
    },
  });

  // After the send the screen reads the trial until its result comes.
  const status = useQuery({
    queryKey: ["instant-trial", trial.trial_id],
    queryFn: () => api.getInstantTrial(trial.date, trial.trial_id),
    enabled: sent,
    refetchInterval: (query) =>
      query.state.data?.status === "settled" ? false : INSTANT_POLL_MS,
  });
  const read = status.data;
  const result: InstantSettled | null =
    read !== undefined && read.status === "settled" ? read : null;
  const pending: InstantPending | null =
    read !== undefined && read.status === "pending" ? read : null;
  const pulseTime = pending?.pulse_time ?? receipt?.pulse_time ?? null;

  // The record of the owner changes with the result.
  const settledSeen = useRef(false);
  const { onSettled } = props;
  useEffect(() => {
    if (result !== null && !settledSeen.current) {
      settledSeen.current = true;
      onSettled();
    }
  }, [result, onSettled]);

  const onCommitStroke = (points: Point[]) => {
    const id = nextStrokeId.current;
    nextStrokeId.current += 1;
    setHistory((h) =>
      pushDoc(h, addStroke(current(h), points, colorIndex, id)),
    );
  };

  // One erase gesture is one step of the history, and the counter
  // moves past the identifiers of the eraser's pieces.
  const onCommitErase = (next: SketchDoc, nextId: number) => {
    nextStrokeId.current = Math.max(nextStrokeId.current, nextId);
    commit(next);
    setSelection(new Set());
  };

  const onPickStroke = (strokeId: number | null) => {
    if (strokeId === null) {
      return;
    }
    setSelection((old) => {
      const next = new Set(old);
      if (next.has(strokeId)) {
        next.delete(strokeId);
      } else {
        next.add(strokeId);
      }
      return next;
    });
  };

  const makeGroupWith = (label: string) => {
    if (label === "" || selection.size === 0) {
      return;
    }
    commit(makeGroup(doc, [...selection], label));
    setSelection(new Set());
    setMode("draw");
  };

  // Saved as it changes: before the send, this device holds the only
  // copy. After it, the copy shows the sketch beside the result.
  useEffect(() => {
    const timer = setTimeout(() => {
      const draft = {
        trialId: trial.trial_id,
        doc,
        impressions,
        typedWord,
        nextStrokeId: nextStrokeId.current,
      };
      if (hasContent(draft)) {
        writeInstantDraft(draft);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [trial.trial_id, doc, impressions, typedWord]);

  // The mirror of the server's refusals: no-scoreable-atom, min-strokes.
  const typed = typedWord.trim();
  const block = sendBlock(
    doc.strokes.length,
    impressions.length > 0 || typed !== "",
    props.view.min_strokes,
  );
  const sendable = block === null;

  // Closing the part while lines are picked gives the pen back.
  const [labelOpen, setLabelOpen] = useState(false);
  const toggleLabel = (): void => {
    if (labelOpen && mode === "select") {
      setMode("draw");
      setSelection(new Set());
    }
    setLabelOpen((old) => !old);
  };

  return (
    <div className={result === null ? "workspace" : "workspace has-result"}>
      <section className="play-day" aria-label="Instant trial">
        <PlaySwitch view="instant" />
        <DayCode code={trial.trial_code} />
        <div className="play-day-meta">
          <p className="muted">
            {sent
              ? "Sent. One send for each code."
              : `Instant trial. ${props.view.left_today} of ${props.view.day_cap} left today.`}
          </p>
        </div>
      </section>

      <CanvasPanel
        doc={doc}
        selection={selection}
        mode={mode}
        colorIndex={colorIndex}
        onPickColor={setColorIndex}
        onCommitStroke={onCommitStroke}
        onCommitErase={onCommitErase}
        nextStrokeId={() => nextStrokeId.current}
        onPickStroke={onPickStroke}
        canUndo={canUndo(history)}
        canRedo={canRedo(history)}
        onUndo={() => {
          setHistory((h) => undo(h));
          setSelection(new Set());
        }}
        onRedo={() => {
          setHistory((h) => redo(h));
          setSelection(new Set());
        }}
        onClear={() => {
          commit(clearSketch(doc));
          setSelection(new Set());
          setMode("draw");
        }}
        disabled={send.isPending || sent}
        hint={
          sent
            ? ""
            : mode === "select"
              ? "Tap the lines that belong together."
              : ""
        }
        emptyNote={
          sent
            ? "Your sketch is on the device you sent it from."
            : "Sketch and describe what comes to mind for this code, then send."
        }
      />

      <aside className="side-cell" aria-label="Instant trial">
        {result !== null ? (
          <InstantResult
            result={result}
            date={trial.date}
            guest={props.view.kind === "guest"}
            canPlayAgain={props.view.left_today > 0}
            onAgain={props.onAgain}
          />
        ) : sent ? (
          <InstantWait
            pulseTime={pulseTime}
            beaconRound={pending?.beacon_round ?? receipt?.beacon_round ?? null}
            error={status.isError ? friendlyMessage(status.error) : null}
          />
        ) : (
          <div className="side-panel">
            <div className="side-scroll">
              <ImpressionsCard
                impressions={impressions}
                input={typedWord}
                onInputChange={setTypedWord}
                onAdd={(text) => setImpressions((rows) => [...rows, text])}
                onRemoveAt={(index) =>
                  setImpressions((rows) => rows.filter((_, at) => at !== index))
                }
              />
              <div className="side-opts">
                <span className="subtle tiny">Optional</span>
                <button
                  type="button"
                  className="btn btn-ghost side-opt"
                  aria-expanded={labelOpen}
                  aria-controls="label-parts"
                  onClick={toggleLabel}
                >
                  <Plus size={14} aria-hidden="true" />
                  {doc.groups.length > 0
                    ? `Label parts (${doc.groups.length})`
                    : "Label parts"}
                </button>
              </div>
              {labelOpen ? (
                <section
                  id="label-parts"
                  className="side-part"
                  aria-label="Label parts of your sketch"
                >
                  <GroupControls
                    doc={doc}
                    mode={mode}
                    selectionSize={selection.size}
                    onToggleSelect={() => {
                      setMode((old) => (old === "select" ? "draw" : "select"));
                      setSelection(new Set());
                    }}
                    onMakeGroup={makeGroupWith}
                  />
                </section>
              ) : null}
            </div>
            <section className="action-bar send-bar" aria-label="Send">
              {sendable ? null : (
                <p className="send-bar-facts">
                  <span className="send-bar-note">
                    {sendBlockHint(block, props.view.min_strokes)}
                  </span>
                </p>
              )}
              <button
                type="button"
                className="btn btn-primary btn-large btn-block send-bar-buttons"
                disabled={!sendable || send.isPending}
                onClick={() => {
                  if (sendingRef.current) {
                    return;
                  }
                  sendingRef.current = true;
                  // A typed word counts: the player can see it on the
                  // screen.
                  const words =
                    typed === "" ? impressions : [...impressions, typed];
                  setImpressions(words);
                  setTypedWord("");
                  send.mutate(words);
                }}
              >
                {send.isPending ? "Sending…" : "Send"}
              </button>
              <div className="send-bar-after">
                <p className="subtle tiny send-bar-hint">
                  The photo is picked a few seconds after you send, so nobody
                  knows it yet. One send for each code. It is saved and public.
                </p>
                <PlayHow />
                {send.isError ? (
                  <div className="notice notice-bad" role="alert">
                    {friendlyMessage(send.error)}
                  </div>
                ) : null}
              </div>
            </section>
          </div>
        )}
      </aside>
      {result === null || result.report.length === 0 ? null : (
        <div className="workspace-wide">
          <WordMatches rows={result.report} />
        </div>
      )}
    </div>
  );
}

/** The seconds from now to a Unix time, counted on this device. */
function useSecondsTo(unixSeconds: number | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (unixSeconds === null) {
      return;
    }
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [unixSeconds]);
  return unixSeconds === null
    ? null
    : Math.max(0, Math.ceil(unixSeconds - now / 1000));
}

function InstantWait(props: {
  pulseTime: number | null;
  beaconRound: number | null;
  error: string | null;
}): React.JSX.Element {
  const seconds = useSecondsTo(props.pulseTime);
  return (
    <section className="instant-wait" aria-label="Waiting for the photo">
      <h2 className="instant-score-label">Sent</h2>
      <p role="status">
        {seconds === null || seconds === 0
          ? "Picking the photo…"
          : `The photo is picked in ${seconds} ${seconds === 1 ? "second" : "seconds"}.`}
      </p>
      <p className="muted small">
        A public random number picks it
        {props.beaconRound === null
          ? ""
          : ` (drand pulse ${props.beaconRound})`}
        . That number did not exist when you sent, so nobody could know the
        photo.
      </p>
      {props.error === null ? null : (
        <div className="notice notice-bad" role="alert">
          {props.error}
        </div>
      )}
    </section>
  );
}

/**
 * `Share` gives the address of the public page of the trial (spec IM1
 * §10 and §16). A test season has no public page, so it has no control.
 */
function ShareTrial(props: {
  date: string;
  trialId: string;
}): React.JSX.Element | null {
  const api = useApi();
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const [said, setSaid] = useState("");
  if (about.data === undefined || about.data.test_season) {
    return null;
  }
  const address = trialAddress(props.date, props.trialId);
  return (
    <>
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => {
          void shareAddress(address, "My Starvector instant trial").then(
            (outcome) =>
              setSaid(
                outcome === "copied"
                  ? "Link copied."
                  : outcome === "failed"
                    ? address
                    : "",
              ),
          );
        }}
      >
        Share
      </button>
      <span className="subtle tiny" role="status">
        {said}
      </span>
    </>
  );
}

function InstantResult(props: {
  result: InstantSettled;
  date: string;
  guest: boolean;
  canPlayAgain: boolean;
  onAgain: () => void;
}): React.JSX.Element {
  const api = useApi();
  const { result } = props;
  const trial = result.trial;
  const pick = result.pick;
  return (
    <div className="instant-result">
      <div className="instant-photo">
        <div className="picture-frame">
          <img
            src={api.imageUrl(result.target_id)}
            alt={result.credit?.title ?? "The photo of this instant trial"}
          />
        </div>
        <Credit credit={result.credit} />
      </div>
      <section className="instant-score" aria-label="Instant result">
        <h2 className="instant-score-label">Instant result</h2>
        <div className="figure instant-number">{percentBeaten(trial.p)}%</div>
        <p>
          Your sketch matched this photo better than {trial.beaten} of the other{" "}
          {trial.decoy_count} photos.
        </p>
        <ChanceMeter p={trial.p} />
        <p className="muted small">
          It was your {ordinal(trial.target_rank)}-closest match. Chance is 50%,
          and this trial is in your public record.
        </p>
        <div className="row">
          <button
            type="button"
            className="btn btn-primary"
            onClick={props.onAgain}
          >
            {props.canPlayAgain ? "Again" : "Done"}
          </button>
          <ShareTrial date={props.date} trialId={result.trial_id} />
        </div>
        <details className="instant-pick">
          <summary>How this photo was picked</summary>
          <dl className="fact-list">
            <dt>Beacon pulse</dt>
            <dd>
              {pick.beacon_chain} #{pick.beacon_round}
            </dd>
            <dt>Position in the pool</dt>
            <dd>
              {pick.target_index} of {pick.pool_count}
            </dd>
            <dt>Randomness</dt>
            <dd className="mono-wrap">{pick.randomness}</dd>
            <dt>Digest of your send</dt>
            <dd className="mono-wrap">{pick.send_digest}</dd>
            <dt>Server value, committed before the pulse</dt>
            <dd className="mono-wrap">{pick.nonce}</dd>
          </dl>
        </details>
        {props.guest ? <GuestInvitation /> : null}
      </section>
    </div>
  );
}
