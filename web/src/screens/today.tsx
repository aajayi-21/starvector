/**
 * Today's sketch (mock 1a, spec W1 B6; layout and copy per spec
 * BR1 §6): the Today view of the Play place, under the switch it
 * shares with practice (ui/play-switch.tsx). The eye goes to two
 * places: the canvas, and the one Send button. Views: no day, open,
 * sent, closing or closed, and revealed (hand-off to the results
 * screen).
 *
 * The open view has three columns that share the width of the page:
 * the day (its code, its close, and the one instruction), the canvas,
 * and the words. Labeling parts and notes are optional rows that open.
 * The send bar ends the words column on a wide screen and is pinned
 * over the tab bar on a phone, so the one action is always in reach.
 * Nothing but the fields, the buttons, and the canvas has an edge.
 *
 * The send is a mutation with an in-flight lock, behind a review step
 * (spec PL1 §8); drafts stay in localStorage as disposable caches (W1
 * §8). A sketch outlives its day: when the day moves, the sketch stays
 * on the canvas until the player says what to do with it (PL1 §4).
 *
 * The open view sends the start report (spec R1 §4), one time. A send
 * that the server refuses for the notice that results are public keeps
 * the sketch and reads `me` again, and the shell then shows the notice
 * screen (spec R1 §3.3).
 */

import { CaretRight } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { useApi } from "../api/client";
import { useDayQuery } from "../api/day-query";
import { reportDayStart } from "../api/day-start";
import type { DayView, SubmissionAck, WireRecord } from "../api/types";
import { ApiError, friendlyMessage, isRefusal } from "../api/types";
import { CanvasPanel } from "../intake/canvas-panel";
import type { Draft } from "../intake/drafts";
import {
  draftKey,
  findEarlierDraft,
  hasContent,
  readDraft,
  readSent,
  removeEarlierDrafts,
  removeStorage,
  sentKey,
  writeStorage,
} from "../intake/drafts";
import { GroupControls } from "../intake/groups-card";
import { ImpressionsCard } from "../intake/impressions-card";
import { sendBlock, sendBlockHint } from "../intake/send-gate";
import { ReplayCanvas } from "../sketch/canvas";
import type { DocHistory, Point, SketchDoc } from "../sketch/core";
import {
  addRelation,
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
  removeRelation,
  serialize,
  undo,
} from "../sketch/core";
import { DayCode } from "../ui/code-cells";
import { useRemaining } from "../ui/countdown";
import { useDayNames } from "../ui/day-names";
import {
  formatCloseAt,
  formatCloseClock,
  formatCloseMoment,
  formatRemaining,
} from "../ui/format";
import { isPostClose } from "../ui/pick-copy";
import { PlayFrame, PlayMessage } from "../ui/play-switch";
import { SendCount } from "../ui/send-count";
import { ShareSketchButton } from "../ui/share-button";

const DRAFT_DEBOUNCE_MS = 500;

const RELATION_WORDING: Record<string, string> = {
  "left-of": "is left of",
  "right-of": "is right of",
  above: "is above",
  below: "is below",
};

const wordingOf = (name: string): string =>
  RELATION_WORDING[name] ?? `is ${name}`;

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** The cause of a send refused for the notice (spec R1 §3.3). */
const NOTICE_CAUSE = "notice";

/**
 * The words for a failed send. A send refused for the notice says
 * that the sketch stays: the general line for that cause does not.
 */
function sendMessage(error: unknown): string {
  return error instanceof ApiError && error.refusalCause === NOTICE_CAUSE
    ? "Before you send, you need to agree that your results are public. Your sketch and words are still here."
    : friendlyMessage(error);
}

export function TodayScreen(): React.JSX.Element {
  return (
    <PlayFrame>
      <TodayView />
    </PlayFrame>
  );
}

function TodayView(): React.JSX.Element {
  const day = useDayQuery();

  if (day.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading today…
      </p>
    );
  }
  if (day.isError || day.data === undefined) {
    if (!isRefusal(day.error)) {
      return (
        <PlayMessage title="Today">
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(day.error)}
          </div>
        </PlayMessage>
      );
    }
    return (
      <PlayMessage title="No day is open right now">
        <p className="muted">
          The next day starts soon. Meanwhile, you can practice on a past photo.
        </p>
        <div>
          <Link to="/practice" className="btn btn-secondary">
            Practice now
          </Link>
        </div>
      </PlayMessage>
    );
  }
  const view = day.data;
  if (view.status === "revealed") {
    return <Navigate to="/reveal" />;
  }
  if (view.submitted) {
    return <SentView view={view} />;
  }
  if (view.status === "closing" || view.status === "closed") {
    const unsent = readDraft(view.day);
    return (
      <PlayMessage title="Today has closed">
        <p className="muted">
          Results are being worked out. The photo appears here in a few minutes,
          and this page updates by itself.
        </p>
        {unsent !== null && hasContent(unsent) ? (
          <p className="muted">
            Your unsent sketch wasn't scored. It's saved on this device, and you
            can use it for the next day.
          </p>
        ) : null}
      </PlayMessage>
    );
  }
  return <OpenWorkspace view={view} />;
}

/**
 * When the day closes, in the reader's zone: the clock time and the
 * countdown while the close is ahead ("Closes tomorrow at 4:00 PM, in
 * 23 h"), the close moment when it is not, and nothing when the day
 * carries no close time.
 */
function closeLine(day: DayView, remaining: number | null): string | null {
  if (remaining !== null && typeof day.closes_at === "string") {
    const now = Date.parse(day.closes_at) - remaining;
    return `Closes ${formatCloseAt(day.closes_at, now)}, in ${formatRemaining(remaining)}`;
  }
  const close = formatCloseMoment(day.closes_at);
  return close === null ? null : `C${close.slice(1)}`;
}

/**
 * The day, in the first column: its code as plain type, its close, and
 * what the player adds below them. The day in play has no calendar
 * date (ui/day-names.ts): the close says when it ends. A day with no
 * close time shows the date of its label. On a phone the code and the
 * close share one line, and the label and the date give way.
 */
function DayBrief(props: {
  view: DayView;
  children?: React.ReactNode;
}): React.JSX.Element {
  const { view } = props;
  const remaining = useRemaining(view.closes_at);
  const names = useDayNames();
  const close = closeLine(view, remaining);
  return (
    <section className="play-brief" aria-label="Today">
      <p className="subtle small play-brief-label">Today's code</p>
      <DayCode code={view.trial_code} />
      {close === null ? (
        <p className="play-brief-date">{names.long(view.day)}</p>
      ) : (
        <p className="muted play-brief-close">{close}</p>
      )}
      <hr className="divider play-brief-rule" />
      {props.children}
      <SendCount
        day={view}
        className="muted small play-brief-count"
        testId="play-brief-count"
      />
    </section>
  );
}

/**
 * After the send: what this device sent, when the photo is revealed,
 * and the steps between. The sketch and the words are the player's
 * own, read from this device, and no score is in them (I7).
 */
function SentView(props: { view: DayView }): React.JSX.Element {
  const { view } = props;
  const remaining = useRemaining(view.closes_at);
  const [record] = useState(() => readSent(view.day));
  const postClose = isPostClose(view.protocol);
  // The close against the reader's clock: "4:00 PM", "tomorrow 4:00 PM".
  const now =
    remaining === null || typeof view.closes_at !== "string"
      ? null
      : Date.parse(view.closes_at) - remaining;
  const closes =
    now === null ? null : formatCloseClock(view.closes_at as string, now);
  const closesAt =
    now === null ? null : formatCloseAt(view.closes_at as string, now);
  return (
    <div className="sent">
      <DayBrief view={view} />

      <section className="sent-main" aria-labelledby="sent-heading">
        <h1 id="sent-heading">Sent. You're in for today</h1>
        <p className="sent-lead">
          {remaining === null || closesAt === null
            ? "The photo is revealed when the day closes."
            : `The photo is revealed ${closesAt}, in ${formatRemaining(remaining)}.`}
        </p>

        <ol className="step-list sent-steps" aria-label="What happens next">
          <li className="step-item is-current">
            <span className="step-icon" aria-hidden="true" />
            <span className="step-text">
              Your sketch is locked in for today
            </span>
          </li>
          <li className="step-item is-pending">
            <span className="step-icon" aria-hidden="true" />
            <span className="step-text">
              The day closes for everyone
              {closes === null ? null : (
                <span className="muted small">{closes}</span>
              )}
            </span>
          </li>
          {/* Only a day with the pick after the close has this step: on
              an earlier day the photo was picked before the day opened. */}
          {postClose ? (
            <li className="step-item is-pending">
              <span className="step-icon" aria-hidden="true" />
              <span className="step-text">
                A public random number picks the photo
              </span>
            </li>
          ) : null}
          <li className="step-item is-pending">
            <span className="step-icon" aria-hidden="true" />
            <span className="step-text">You see the photo and your result</span>
          </li>
        </ol>

        <div className="sent-next">
          <Link to="/practice" className="btn btn-secondary">
            Practice while you wait
          </Link>
          {/* The player's own sketch, as an image for friends, before
              the reveal (spec SS1 §6). */}
          <ShareSketchButton day={view.day} postClose={postClose} />
          <Link to="/">Back to home</Link>
        </div>
      </section>

      {record === null ? null : (
        <section className="sent-record" aria-labelledby="sent-what">
          <h2 id="sent-what">What you sent</h2>
          {record.canvas_strokes.length === 0 ? null : (
            <div className="sent-sketch" aria-hidden="true">
              <ReplayCanvas strokes={record.canvas_strokes} />
            </div>
          )}
          {record.impressions.length === 0 ? null : (
            <div>
              <span className="subtle small">Words</span>
              <ul className="sent-words" aria-label="Your words">
                {record.impressions.map((word, index) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: duplicates allowed
                  <li key={`${word}-${index}`}>{word}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function OpenWorkspace(props: { view: DayView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const names = useDayNames();
  const { view } = props;

  // The drawing screen shows the open day: tell the server one time
  // (spec R1 §4). The sent, closed, and revealed views do not come
  // here, thus they send no report.
  useEffect(() => {
    reportDayStart(api, view.player, view.day);
  }, [api, view.player, view.day]);

  // Read one time: a draft for this day, or the newest unsent one from a
  // day that has closed, which comes back with its day named.
  const [restored] = useState(() => {
    const own = readDraft(view.day);
    return own !== null && hasContent(own)
      ? { day: view.day, draft: own }
      : findEarlierDraft(view.day);
  });
  const restoredDraft = restored?.draft ?? null;
  const [draftDay, setDraftDay] = useState(restored?.day ?? view.day);
  const [history, setHistory] = useState<DocHistory>(() =>
    historyOf(restoredDraft?.doc ?? EMPTY_DOC),
  );
  const [selection, setSelection] = useState<ReadonlySet<number>>(
    () => new Set<number>(),
  );
  const [mode, setMode] = useState<"draw" | "select">("draw");
  const [colorIndex, setColorIndex] = useState(0);
  const [impressions, setImpressions] = useState<string[]>(
    () => restoredDraft?.impressions ?? [],
  );
  const [pastedText, setPastedText] = useState(
    () => restoredDraft?.pastedText ?? "",
  );
  const [typedWord, setTypedWord] = useState(
    () => restoredDraft?.typedWord ?? "",
  );
  const [reviewing, setReviewing] = useState(false);
  const [includeTyped, setIncludeTyped] = useState(true);
  const [relationFirst, setRelationFirst] = useState("");
  const [relationName, setRelationName] = useState(
    () => view.relation_vocabulary[0] ?? "",
  );
  const [relationSecond, setRelationSecond] = useState("");
  const [draftSaved, setDraftSaved] = useState(false);
  const nextStrokeId = useRef(restoredDraft?.nextStrokeId ?? 1);

  const doc = current(history);
  const commit = (next: SketchDoc) => setHistory((h) => pushDoc(h, next));

  // isPending flips a task late (the query notify scheduler), so the
  // double-POST lock lives in a ref the click handler checks first.
  const sendingRef = useRef(false);
  const [sentDay, setSentDay] = useState<string | null>(null);

  const forgetDraft = () => {
    setHistory(historyOf(EMPTY_DOC));
    setImpressions([]);
    setPastedText("");
    setTypedWord("");
    setSelection(new Set());
    setMode("draw");
    setReviewing(false);
    setIncludeTyped(true);
  };

  const send = useMutation<
    SubmissionAck,
    Error,
    { day: string; record: WireRecord }
  >({
    mutationFn: ({ day, record }) => api.submit(day, record),
    onSuccess: (_ack, { day, record }) => {
      setSentDay(day);
      writeStorage(sentKey(day), record);
      removeStorage(draftKey(draftDay));
      removeEarlierDrafts(day);
      forgetDraft();
      // The day now reads "sent" on each screen that shows it, and
      // the sketches of the day are open to this player (spec SS1 §4).
      void queryClient.invalidateQueries({ queryKey: ["day"] });
      void queryClient.invalidateQueries({ queryKey: ["day-sends"] });
    },
    onError: (error, { day }) => {
      if (!(error instanceof ApiError)) {
        return;
      }
      if (error.refusalCause === "already-submitted") {
        setSentDay(day);
        return;
      }
      if (
        error.refusalCause === "day-moved" ||
        error.refusalCause === "day-closed"
      ) {
        // The stale tab: nothing was spent, and the sketch stays. The
        // screen follows the day as soon as the read comes back.
        setReviewing(false);
        void queryClient.invalidateQueries({ queryKey: ["day"] });
      }
      if (error.refusalCause === NOTICE_CAUSE) {
        // Nothing was stored, and the sketch stays. The read of me
        // brings the notice screen, and the save at unmount keeps the
        // sketch on this device for the way back.
        setReviewing(false);
        void queryClient.invalidateQueries({ queryKey: ["me"] });
      }
    },
    onSettled: () => {
      sendingRef.current = false;
    },
  });

  const sent = sentDay === view.day;
  const empty = !hasContent({ doc, impressions, pastedText, typedWord });
  const dayMoved = draftDay !== view.day;

  // An empty workspace has nothing to ask about, so it just follows the
  // day. A sketch waits for the player's choice below.
  useEffect(() => {
    if (dayMoved && empty) {
      setDraftDay(view.day);
    }
  }, [dayMoved, empty, view.day]);

  // The draft as of this render, for the save at unmount: the workspace
  // leaves the page when the day closes, and a timer does not fire then.
  const latestDraft = useRef({
    day: draftDay,
    doc,
    impressions,
    pastedText,
    typedWord,
  });
  latestDraft.current = {
    day: draftDay,
    doc,
    impressions,
    pastedText,
    typedWord,
  };
  useEffect(
    () => () => {
      const { day, ...rest } = latestDraft.current;
      if (hasContent(rest)) {
        writeStorage(draftKey(day), {
          ...rest,
          nextStrokeId: nextStrokeId.current,
        } satisfies Draft);
      }
    },
    [],
  );

  // Debounced draft autosave, cleared on send (§8). The sent gate
  // keeps a pending timer from writing the draft back after the
  // send's onSuccess removed it. The draft stays under the day it was
  // drawn for until the player moves it.
  useEffect(() => {
    if (sent) {
      return;
    }
    const timer = setTimeout(() => {
      writeStorage(draftKey(draftDay), {
        doc,
        impressions,
        pastedText,
        typedWord,
        nextStrokeId: nextStrokeId.current,
      } satisfies Draft);
      setDraftSaved(true);
    }, DRAFT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [doc, impressions, pastedText, typedWord, draftDay, sent]);

  if (sent) {
    return <SentView view={view} />;
  }

  const typed = typedWord.trim();
  const hasWords =
    impressions.length > 0 || pastedText.trim() !== "" || typed !== "";
  const block = sendBlock(doc.strokes.length, hasWords, view.min_strokes);
  const scoreable = block === null;
  const sendWords =
    typed !== "" && includeTyped ? [...impressions, typed] : impressions;
  const sendReady =
    sendBlock(
      doc.strokes.length,
      sendWords.length > 0 || pastedText.trim() !== "",
      view.min_strokes,
    ) === null;

  const keepForToday = () => {
    removeStorage(draftKey(draftDay));
    setDraftDay(view.day);
    send.reset();
  };

  const startClean = () => {
    removeStorage(draftKey(draftDay));
    forgetDraft();
    setDraftDay(view.day);
    send.reset();
  };

  const onCommitStroke = (points: Point[]) => {
    const id = nextStrokeId.current;
    nextStrokeId.current += 1;
    // Build on the freshest snapshot, not the render closure — two
    // commits in one batch must not erase each other.
    setHistory((h) =>
      pushDoc(h, addStroke(current(h), points, colorIndex, id)),
    );
  };

  // One erase gesture is one step of the history. The eraser's pieces
  // took new identifiers, so the counter moves past them and no
  // identifier is used twice, also after an undo.
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

  const resetPicks = () => {
    setSelection(new Set());
    setRelationFirst("");
    setRelationSecond("");
  };

  const makeGroupWith = (label: string) => {
    if (label === "" || selection.size === 0) {
      return;
    }
    commit(makeGroup(doc, [...selection], label));
    setSelection(new Set());
    setMode("draw");
  };

  const groupExists = (id: string): boolean =>
    doc.groups.some((group) => group.id === id);

  const relationReady =
    relationFirst !== "" &&
    relationSecond !== "" &&
    relationFirst !== relationSecond &&
    relationName !== "" &&
    groupExists(relationFirst) &&
    groupExists(relationSecond);

  const addRelationNow = () => {
    if (!relationReady) {
      // Undo can rewind a group out from under the selects.
      setRelationFirst("");
      setRelationSecond("");
      return;
    }
    commit(addRelation(doc, relationName, [relationFirst, relationSecond]));
  };

  const groupName = (id: string): string =>
    doc.groups.find((row) => row.id === id)?.label || "a part";

  const labeled = doc.groups.length;
  const summaryParts = [
    plural(impressions.length, "word", "words"),
    plural(doc.strokes.length, "line", "lines"),
    ...(labeled > 0 ? [plural(labeled, "labeled part", "labeled parts")] : []),
    ...(pastedText.trim() !== "" ? ["notes"] : []),
  ];

  // The hint line speaks only while the player picks lines: the day's
  // column holds the one instruction, and an empty canvas says where to
  // draw.
  const sketchHint =
    mode === "select"
      ? selection.size > 0
        ? `${plural(selection.size, "line", "lines")} picked. Name them under “Label parts of your sketch”.`
        : "Tap the lines that belong together."
      : "";

  // The second line of the send bar: why Send is off, or that the
  // draft is safe.
  const barNote = scoreable
    ? draftSaved
      ? "Draft saved on this device"
      : ""
    : sendBlockHint(block, view.min_strokes);

  return (
    <div className="workspace">
      <DayBrief view={view}>
        <p className="play-brief-lead">
          {isPostClose(view.protocol)
            ? "The photo for this code is picked when the day closes."
            : "A photo is hidden behind this code."}{" "}
          Sketch and describe whatever comes to mind.
        </p>
      </DayBrief>

      {dayMoved && !empty ? (
        <section
          className="notice workspace-notice"
          role="alert"
          aria-label="Your earlier sketch"
        >
          <p>
            You started this sketch for {names.long(draftDay)}, and that day has
            closed, so it wasn't scored.{" "}
            {isPostClose(view.protocol)
              ? "A new day has started with a new code."
              : "A new photo is now hidden behind a new code."}
          </p>
          <div className="row">
            <button
              type="button"
              className="btn btn-primary"
              onClick={keepForToday}
            >
              Keep it for today
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={startClean}
            >
              Start clean
            </button>
          </div>
        </section>
      ) : null}

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
          resetPicks();
        }}
        onRedo={() => {
          setHistory((h) => redo(h));
          resetPicks();
        }}
        onClear={() => {
          commit(clearSketch(doc));
          resetPicks();
          setMode("draw");
        }}
        disabled={send.isPending || dayMoved}
        hint={sketchHint}
      />

      <aside className="side-cell" aria-label="Your answer">
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

            <div className="row-list side-rows">
              <details className="row-disclosure">
                <summary>
                  Label parts of your sketch
                  <OptionalMark />
                </summary>
                <div className="row-body">
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
                  {labeled < 2 ? null : (
                    <>
                      <hr className="divider" />
                      <div className="label">Where things are</div>
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "1fr 1fr 1fr",
                          gap: 6,
                        }}
                      >
                        <select
                          className="input"
                          aria-label="first part"
                          value={relationFirst}
                          onChange={(event) =>
                            setRelationFirst(event.target.value)
                          }
                        >
                          <option value="">Pick…</option>
                          {doc.groups.map((group) => (
                            <option key={group.id} value={group.id}>
                              {group.label}
                            </option>
                          ))}
                        </select>
                        <select
                          className="input"
                          aria-label="position"
                          value={relationName}
                          onChange={(event) =>
                            setRelationName(event.target.value)
                          }
                        >
                          {view.relation_vocabulary.map((name) => (
                            <option key={name} value={name}>
                              {wordingOf(name)}
                            </option>
                          ))}
                        </select>
                        <select
                          className="input"
                          aria-label="second part"
                          value={relationSecond}
                          onChange={(event) =>
                            setRelationSecond(event.target.value)
                          }
                        >
                          <option value="">Pick…</option>
                          {doc.groups.map((group) => (
                            <option key={group.id} value={group.id}>
                              {group.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          disabled={!relationReady}
                          onClick={addRelationNow}
                        >
                          Add
                        </button>
                      </div>
                      {doc.relations.length === 0 ? null : (
                        <ul
                          className="stack-sm"
                          style={{ margin: 0, padding: 0, listStyle: "none" }}
                        >
                          {doc.relations.map((relation, index) => (
                            <li
                              key={`${relation.relation}-${relation.of[0]}-${relation.of[1]}-${
                                // biome-ignore lint/suspicious/noArrayIndexKey: duplicates allowed
                                index
                              }`}
                              className="row-between"
                            >
                              <span>
                                {groupName(relation.of[0])}{" "}
                                {wordingOf(relation.relation)}{" "}
                                {groupName(relation.of[1])}
                              </span>
                              <button
                                type="button"
                                className="btn btn-ghost"
                                aria-label="Remove this position"
                                onClick={() =>
                                  commit(removeRelation(doc, index))
                                }
                              >
                                Remove
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  )}
                </div>
              </details>

              <details className="row-disclosure">
                <summary>
                  Notes
                  <OptionalMark />
                </summary>
                <div className="row-body">
                  <textarea
                    className="input"
                    aria-label="Notes"
                    placeholder="Paste or type longer notes here."
                    value={pastedText}
                    onChange={(event) => setPastedText(event.target.value)}
                  />
                </div>
              </details>
            </div>
          </div>
          <section
            className={
              reviewing
                ? "action-bar send-bar is-reviewing"
                : "action-bar send-bar"
            }
            aria-label="Send"
          >
            <p className="send-bar-facts">
              <span>{summaryParts.join(", ")}</span>
              <span className="send-bar-note">{barNote}</span>
            </p>
            {reviewing ? (
              <ReviewPanel
                words={impressions}
                strokes={doc.strokes.length}
                labeled={labeled}
                notes={pastedText.trim() !== ""}
                typed={typed}
                includeTyped={includeTyped}
                onIncludeTyped={setIncludeTyped}
              />
            ) : null}
            {reviewing ? (
              <div className="stack-sm send-bar-buttons">
                <button
                  type="button"
                  className="btn btn-primary btn-large btn-block"
                  disabled={!sendReady || send.isPending || dayMoved}
                  onClick={() => {
                    if (sendingRef.current) {
                      return;
                    }
                    sendingRef.current = true;
                    send.mutate({
                      day: view.day,
                      record: serialize(doc, sendWords, pastedText),
                    });
                  }}
                >
                  {send.isPending ? "Sending…" : "Send my sketch"}
                </button>
                <button
                  type="button"
                  className="btn btn-secondary btn-block"
                  disabled={send.isPending}
                  onClick={() => setReviewing(false)}
                >
                  Keep editing
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="btn btn-primary btn-large btn-block send-bar-buttons"
                disabled={!scoreable || dayMoved}
                onClick={() => {
                  setIncludeTyped(true);
                  send.reset();
                  setReviewing(true);
                }}
              >
                Review and send
              </button>
            )}
            <p className="subtle tiny send-bar-hint">
              You get one send, and you can't change it after.
            </p>
            {send.isError && !sent ? (
              <div className="notice notice-bad" role="alert">
                {sendMessage(send.error)}
              </div>
            ) : null}
          </section>
        </div>
      </aside>
    </div>
  );
}

/** The mark of a part the player can skip, with the row's chevron. */
function OptionalMark(): React.JSX.Element {
  return (
    <span className="row-meta">
      Optional
      <CaretRight size={16} aria-hidden="true" className="row-chevron" />
    </span>
  );
}

/** What this send holds, in the player's words (spec PL1 §8). */
function ReviewPanel(props: {
  words: ReadonlyArray<string>;
  strokes: number;
  labeled: number;
  notes: boolean;
  typed: string;
  includeTyped: boolean;
  onIncludeTyped: (include: boolean) => void;
}): React.JSX.Element {
  const { words, strokes, labeled, notes, typed, includeTyped } = props;
  return (
    <section className="stack-sm" aria-label="Review your send">
      <h3>Check before you send</h3>
      <p className="small">
        <strong>Words:</strong> {words.length === 0 ? "none" : words.join(", ")}
      </p>
      <p className="small">
        <strong>Sketch:</strong>{" "}
        {strokes === 0
          ? "none"
          : `${plural(strokes, "line", "lines")}${
              labeled > 0
                ? `, ${plural(labeled, "labeled part", "labeled parts")}`
                : ""
            }`}
      </p>
      {notes ? (
        <p className="small">
          <strong>Notes:</strong> included
        </p>
      ) : null}
      {typed === "" ? null : (
        <label className="small row" style={{ flexWrap: "nowrap", gap: 8 }}>
          <input
            type="checkbox"
            checked={includeTyped}
            onChange={(event) => props.onIncludeTyped(event.target.checked)}
          />
          <span>
            Include “{typed}”. You typed it but didn't add it to your words.
          </span>
        </label>
      )}
    </section>
  );
}
