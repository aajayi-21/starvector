/**
 * Today's session (mock 1a, spec W1 B6; layout and copy per spec
 * BR1 §6). The eye goes to two places: the canvas, and the one Send
 * button. Words sit beside the canvas; labeling parts and notes are
 * optional and fold away. Views: no day, open, sent, closing or
 * closed, and revealed (hand-off to the results screen).
 *
 * The send is a mutation with an in-flight lock; drafts stay in
 * localStorage as disposable caches (W1 §8).
 */

import { CheckCircle } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, Navigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { useApi } from "../api/client";
import type { DayView, WireRecord } from "../api/types";
import { ApiError, friendlyMessage, isRefusal } from "../api/types";
import { CanvasPanel } from "../intake/canvas-panel";
import { GroupControls } from "../intake/groups-card";
import { ImpressionsCard } from "../intake/impressions-card";
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
import { formatDay } from "../ui/format";

const DRAFT_DEBOUNCE_MS = 500;

const RELATION_WORDING: Record<string, string> = {
  "left-of": "is left of",
  "right-of": "is right of",
  above: "is above",
  below: "is below",
};

const wordingOf = (name: string): string =>
  RELATION_WORDING[name] ?? `is ${name}`;

interface Draft {
  doc: SketchDoc;
  impressions: string[];
  pastedText: string;
  nextStrokeId: number;
}

const draftKey = (day: string): string => `sv:draft:${day}`;
const sentKey = (day: string): string => `sv:sent:${day}`;

function readDraft(day: string): Draft | null {
  try {
    const raw = window.localStorage.getItem(draftKey(day));
    return raw === null ? null : (JSON.parse(raw) as Draft);
  } catch {
    return null;
  }
}

/** Drafts are disposable caches (§8) — a failed write is dropped. */
function writeStorage(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage full or blocked: the draft note simply stays quiet.
  }
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
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
  const api = useApi();
  const day = useQuery({
    queryKey: ["day"],
    queryFn: () => api.getDay(),
    refetchOnWindowFocus: true,
  });

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
    return <SentView closesAt={view.closes_at} />;
  }
  if (view.status === "closing" || view.status === "closed") {
    return (
      <MessageCard title="Today's session has closed">
        <p className="muted">
          Results are being worked out. Check back in a few minutes to see the
          photo.
        </p>
      </MessageCard>
    );
  }
  return <OpenWorkspace key={view.day} view={view} />;
}

function SentView(props: {
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
          Your sketch is locked in. The photo is revealed when the day closes
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

  const restored = useMemo(() => readDraft(view.day), [view.day]);
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
  const [pastedText, setPastedText] = useState(
    () => restored?.pastedText ?? "",
  );
  const [relationFirst, setRelationFirst] = useState("");
  const [relationName, setRelationName] = useState(
    () => view.relation_vocabulary[0] ?? "",
  );
  const [relationSecond, setRelationSecond] = useState("");
  const [draftSaved, setDraftSaved] = useState(false);
  const nextStrokeId = useRef(restored?.nextStrokeId ?? 1);

  const doc = current(history);
  const commit = (next: SketchDoc) => setHistory((h) => pushDoc(h, next));

  // isPending flips a task late (the query notify scheduler), so the
  // double-POST lock lives in a ref the click handler checks first.
  const sendingRef = useRef(false);
  const send = useMutation({
    mutationFn: (record: WireRecord) => api.submit(record),
    onSuccess: (_ack, record) => {
      writeStorage(sentKey(view.day), record);
      try {
        window.localStorage.removeItem(draftKey(view.day));
      } catch {
        // Disposable cache.
      }
      // The day now reads "sent" on each screen that shows it.
      void queryClient.invalidateQueries({ queryKey: ["day"] });
    },
    onSettled: () => {
      sendingRef.current = false;
    },
  });

  const sent =
    send.isSuccess ||
    (send.error instanceof ApiError &&
      send.error.refusalCause === "already-submitted");

  // Debounced draft autosave, cleared on send (§8). The sent gate
  // keeps a pending timer from writing the draft back after the
  // send's onSuccess removed it.
  useEffect(() => {
    if (sent) {
      return;
    }
    const timer = setTimeout(() => {
      writeStorage(draftKey(view.day), {
        doc,
        impressions,
        pastedText,
        nextStrokeId: nextStrokeId.current,
      } satisfies Draft);
      setDraftSaved(true);
    }, DRAFT_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [doc, impressions, pastedText, view.day, sent]);

  if (sent) {
    return <SentView closesAt={view.closes_at} />;
  }

  const scoreable =
    impressions.length > 0 ||
    doc.strokes.length > 0 ||
    pastedText.trim() !== "";

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
        ? `${plural(selection.size, "stroke", "strokes")} picked — name them on the right.`
        : "Tap the strokes that belong together."
      : doc.strokes.length === 0
        ? "Draw whatever comes to mind. Each line you draw is one stroke."
        : "Keep going, or add words on the right.";

  return (
    <div className="stack-lg">
      <header className="row-between" style={{ alignItems: "flex-end" }}>
        <div className="stack-sm">
          <div className="eyebrow">Today's session · {formatDay(view.day)}</div>
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
          disabled={send.isPending}
          hint={sketchHint}
        />

        <aside className="stack side-panel" aria-label="Your answer">
          <ImpressionsCard
            impressions={impressions}
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
            <button
              type="button"
              className="btn btn-primary btn-large btn-block"
              disabled={!scoreable || send.isPending}
              onClick={() => {
                if (sendingRef.current) {
                  return;
                }
                sendingRef.current = true;
                send.mutate(serialize(doc, impressions, pastedText));
              }}
            >
              {send.isPending ? "Sending…" : "Send today's session"}
            </button>
            <p className="hint">
              {scoreable
                ? "You can send once, and you can't change it after."
                : "Draw something or add a word first."}
              {draftSaved ? " Your draft is saved on this device." : ""}
            </p>
            {send.isError && !sent ? (
              <div className="notice notice-bad" role="alert">
                {friendlyMessage(send.error)}
              </div>
            ) : null}
          </section>
        </aside>
      </div>
    </div>
  );
}
