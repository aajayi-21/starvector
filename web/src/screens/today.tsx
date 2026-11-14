/**
 * Today's session (mock 1a, spec W1 B6; layout and copy per spec
 * BR1 §6). The eye goes to two places: the canvas, and the one Send
 * button. Words sit beside the canvas; labeling parts and notes are
 * optional and fold away. Views: no day, open, sent, closing or
 * closed, and revealed (hand-off to the results screen).
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

import { CheckCircle } from "@phosphor-icons/react";
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
  removeEarlierDrafts,
  removeStorage,
  sentKey,
  writeStorage,
} from "../intake/drafts";
import { GroupControls } from "../intake/groups-card";
import { ImpressionsCard } from "../intake/impressions-card";
import { sendBlock, sendBlockHint } from "../intake/send-gate";
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
import { CodeCells } from "../ui/code-cells";
import { ClosesIn, ClosesInBadge } from "../ui/countdown";
import { formatCloseMoment, formatDay } from "../ui/format";

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

function MessageCard(props: {
  title: string;
  children?: React.ReactNode;
}): React.JSX.Element {
  return (
    <div className="page-narrow" style={{ margin: "0 auto" }}>
      <section className="card card-hero">
        <h2>{props.title}</h2>
        {props.children}
      </section>
    </div>
  );
}

export function TodayScreen(): React.JSX.Element {
  const day = useDayQuery();

  if (day.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading today's session…
      </p>
    );
  }
  if (day.isError || day.data === undefined) {
    if (!isRefusal(day.error)) {
      return (
        <MessageCard title="Today's session">
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(day.error)}
          </div>
        </MessageCard>
      );
    }
    return (
      <MessageCard title="No session is open right now">
        <p className="muted">
          The next day starts soon. Meanwhile, you can practice on a past photo.
        </p>
        <div>
          <Link to="/practice" className="btn btn-secondary">
            Practice
          </Link>
        </div>
      </MessageCard>
    );
  }
  const view = day.data;
  if (view.status === "revealed") {
    return <Navigate to="/reveal" />;
  }
  if (view.submitted) {
    return <SentView day={view.day} closesAt={view.closes_at} />;
  }
  if (view.status === "closing" || view.status === "closed") {
    const unsent = readDraft(view.day);
    return (
      <MessageCard title="Today's session has closed">
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
      </MessageCard>
    );
  }
  return <OpenWorkspace view={view} />;
}

function SentView(props: {
  day: string;
  closesAt?: string | null | undefined;
}): React.JSX.Element {
  return (
    <div className="page-narrow" style={{ margin: "0 auto" }}>
      <section className="card card-hero" aria-labelledby="sent-heading">
        <div className="row" style={{ color: "var(--good)" }}>
          <CheckCircle size={32} weight="fill" aria-hidden="true" />
          <h2 id="sent-heading" style={{ color: "var(--text)" }}>
            Sent — you're in for today
          </h2>
        </div>
        <p className="muted">
          Your sketch is locked in for the session of {formatDay(props.day)}.
          The photo is revealed when the day closes
          <ClosesIn closesAt={props.closesAt} prefix=" — in" />.
        </p>
        <div className="row">
          <Link to="/" className="btn btn-primary">
            Back to home
          </Link>
          <Link to="/practice" className="btn btn-secondary">
            Practice while you wait
          </Link>
        </div>
      </section>
    </div>
  );
}

function OpenWorkspace(props: { view: DayView }): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
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
      // The day now reads "sent" on each screen that shows it.
      void queryClient.invalidateQueries({ queryKey: ["day"] });
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
    return <SentView day={view.day} closesAt={view.closes_at} />;
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
    plural(doc.strokes.length, "stroke", "strokes"),
    ...(labeled > 0 ? [plural(labeled, "labeled part", "labeled parts")] : []),
    ...(pastedText.trim() !== "" ? ["notes"] : []),
  ];

  const sketchHint =
    mode === "select"
      ? selection.size > 0
        ? `${plural(selection.size, "stroke", "strokes")} picked — name them under “Label parts of your sketch”.`
        : "Tap the strokes that belong together."
      : doc.strokes.length === 0
        ? "Draw whatever comes to mind. Each line you draw is one stroke."
        : "Keep going, or add some words.";

  return (
    <div className="stack-lg">
      <header className="row-between" style={{ alignItems: "flex-end" }}>
        <div className="stack-sm">
          <div className="eyebrow">
            Today's session ·{" "}
            {formatCloseMoment(view.closes_at) ?? formatDay(view.day)}
          </div>
          <div className="row" style={{ gap: 16 }}>
            <CodeCells code={view.trial_code} />
            <p className="muted" style={{ maxWidth: 360 }}>
              A photo is hidden behind this code. Sketch and describe whatever
              comes to mind.{" "}
              <Link to="/how" className="small">
                How it works
              </Link>
            </p>
          </div>
        </div>
        <ClosesInBadge closesAt={view.closes_at} />
      </header>

      {dayMoved && !empty ? (
        <section
          className="notice"
          role="alert"
          aria-label="Your earlier sketch"
        >
          <p>
            You started this sketch for the session of {formatDay(draftDay)},
            and that session has closed, so it wasn't scored. A new photo is now
            hidden behind a new code.
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

      <div className="workspace">
        <CanvasPanel
          doc={doc}
          selection={selection}
          mode={mode}
          colorIndex={colorIndex}
          onPickColor={setColorIndex}
          onCommitStroke={onCommitStroke}
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

        <aside className="stack side-panel" aria-label="Your answer">
          <ImpressionsCard
            impressions={impressions}
            input={typedWord}
            onInputChange={setTypedWord}
            onAdd={(text) => setImpressions((rows) => [...rows, text])}
            onRemoveAt={(index) =>
              setImpressions((rows) => rows.filter((_, at) => at !== index))
            }
          />

          <details className="card disclosure">
            <summary>
              Label parts of your sketch{" "}
              <span className="subtle" style={{ fontWeight: 500 }}>
                (optional)
              </span>
            </summary>
            <div className="disclosure-body">
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
                      onChange={(event) => setRelationFirst(event.target.value)}
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
                      onChange={(event) => setRelationName(event.target.value)}
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
                            onClick={() => commit(removeRelation(doc, index))}
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

          <details className="card disclosure">
            <summary>
              Notes{" "}
              <span className="subtle" style={{ fontWeight: 500 }}>
                (optional)
              </span>
            </summary>
            <div className="disclosure-body">
              <textarea
                className="input"
                aria-label="Notes"
                placeholder="Paste or type longer notes here."
                value={pastedText}
                onChange={(event) => setPastedText(event.target.value)}
              />
            </div>
          </details>

          <section className="card" aria-label="Send">
            <p className="muted small">{summaryParts.join(" · ")}</p>
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
              <div className="stack-sm">
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
                  {send.isPending ? "Sending…" : "Send today's session"}
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
                className="btn btn-primary btn-large btn-block"
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
            <p className="hint">
              {scoreable
                ? "You can send once, and you can't change it after."
                : sendBlockHint(block, view.min_strokes)}
              {draftSaved ? " Your draft is saved on this device." : ""}
            </p>
            {send.isError && !sent ? (
              <div className="notice notice-bad" role="alert">
                {sendMessage(send.error)}
              </div>
            ) : null}
          </section>
        </aside>
      </div>
    </div>
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
          : `${plural(strokes, "stroke", "strokes")}${
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
