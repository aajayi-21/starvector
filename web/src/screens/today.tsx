/**
 * The daily trial screen (mock 1a, spec W1 B6). Five views: no day,
 * open, submitted, closed, revealed (hand-off to the reveal
 * screen). The send is a mutation with an in-flight lock; drafts
 * stay in localStorage as disposable caches (§8).
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Navigate } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { useApi } from "../api/client";
import type { SubmissionAck, WireRecord } from "../api/types";
import { ApiError, friendlyMessage, isRefusal } from "../api/types";
import { SketchCanvas } from "../sketch/canvas";
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
import { groupDisplay } from "../sketch/palette";
import { Kicker } from "../ui/kicker";
import { PaletteRow } from "../ui/palette-row";
import { TargetCode } from "../ui/target-code";

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

function shortHash(value: string): string {
  return value.length <= 16 ? value : `${value.slice(0, 8)}…${value.slice(-6)}`;
}

function CenteredCard(props: {
  kicker: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <div style={{ padding: 28, maxWidth: 520 }}>
      <div className="card elev-sm">
        <span className="card-kicker">{props.kicker}</span>
        {props.children}
      </div>
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
    return <CenteredCard kicker="Today">Loading…</CenteredCard>;
  }
  if (day.isError || day.data === undefined) {
    if (!isRefusal(day.error)) {
      return (
        <CenteredCard kicker="Today">
          <p className="text-muted" role="alert">
            {friendlyMessage(day.error)}
          </p>
        </CenteredCard>
      );
    }
    return (
      <CenteredCard kicker="No day">
        <p className="text-muted">
          No trial is open. The operator opens the next day.
        </p>
      </CenteredCard>
    );
  }
  const view = day.data;
  if (view.status === "revealed") {
    return <Navigate to="/reveal" />;
  }
  if (view.submitted) {
    return <SubmittedView ack={null} />;
  }
  if (view.status === "closed") {
    return (
      <CenteredCard kicker="Closed">
        <p className="text-muted">
          The day has closed. The reveal opens when the operator scores it.
        </p>
      </CenteredCard>
    );
  }
  return <OpenWorkspace key={view.day} view={view} />;
}

function SubmittedView(props: {
  ack: SubmissionAck | null;
}): React.JSX.Element {
  return (
    <CenteredCard kicker="Submitted">
      <p>Sent. The reveal opens after the day closes.</p>
      {props.ack === null ? null : (
        <p className="text-muted" style={{ fontSize: 13 }}>
          trial{" "}
          <span style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>
            {props.ack.trial_id}
          </span>{" "}
          · {props.ack.atom_count} atoms
        </p>
      )}
      <p className="text-muted" style={{ fontSize: 12 }}>
        One send per day — it locked when it landed.
      </p>
    </CenteredCard>
  );
}

function OpenWorkspace(props: {
  view: {
    day: string;
    trial_code: string;
    commitment: string;
    relation_vocabulary: string[];
    closes_at?: string | null;
  };
}): React.JSX.Element {
  const api = useApi();
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
  const [impressionInput, setImpressionInput] = useState("");
  const [groupLabel, setGroupLabel] = useState("");
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

  if (send.isSuccess) {
    return <SubmittedView ack={send.data} />;
  }
  if (sent) {
    return <SubmittedView ack={null} />;
  }

  const scoreable =
    impressions.length > 0 ||
    doc.strokes.length > 0 ||
    pastedText.trim() !== "";

  const addImpression = () => {
    const text = impressionInput.trim();
    if (text !== "") {
      setImpressions((rows) => [...rows, text]);
      setImpressionInput("");
    }
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

  const makeGroupNow = () => {
    const label = groupLabel.trim();
    if (label === "" || selection.size === 0) {
      return;
    }
    commit(makeGroup(doc, [...selection], label));
    setSelection(new Set());
    setGroupLabel("");
    setMode("draw");
  };

  const groupExists = (id: string): boolean =>
    doc.groups.some((group) => group.id === id);

  const addRelationNow = () => {
    if (
      relationFirst === "" ||
      relationSecond === "" ||
      relationFirst === relationSecond ||
      relationName === "" ||
      !groupExists(relationFirst) ||
      !groupExists(relationSecond)
    ) {
      // Undo can rewind a group out from under the selects.
      setRelationFirst("");
      setRelationSecond("");
      return;
    }
    commit(addRelation(doc, relationName, [relationFirst, relationSecond]));
  };

  const groupName = (id: string): string => {
    const group = doc.groups.find((row) => row.id === id);
    return group === undefined || group.label === ""
      ? id
      : `${group.label} (${id})`;
  };

  const summary = [
    `${impressions.length} impression${impressions.length === 1 ? "" : "s"}`,
    `${doc.strokes.length} stroke${doc.strokes.length === 1 ? "" : "s"}`,
    `${doc.groups.length} group${doc.groups.length === 1 ? "" : "s"}`,
    `${doc.relations.length} relation${doc.relations.length === 1 ? "" : "s"}`,
    ...(pastedText.trim() !== "" ? ["pasted notes"] : []),
  ].join(" · ");

  const sketchHint =
    mode === "select"
      ? selection.size > 0
        ? `${selection.size} selected — name the group, then Group.`
        : "Click a stroke to select it — it gets an accent halo."
      : "Each drag is one stroke. Use Select strokes to group them.";

  return (
    <div
      style={{ display: "flex", flexDirection: "column", minHeight: "100%" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          justifyContent: "space-between",
          gap: 24,
          padding: "22px 28px 18px",
          flexWrap: "wrap",
        }}
      >
        <TargetCode code={view.trial_code} />
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-end",
            gap: 8,
            paddingBottom: 4,
          }}
        >
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span className="tag tag-outline">Open</span>
            {typeof view.closes_at === "string" ? (
              <ClosesIn closesAt={view.closes_at} />
            ) : null}
          </div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            trial {view.day} · commitment{" "}
            <span
              title={view.commitment}
              style={{
                fontFamily: "ui-monospace, Menlo, monospace",
                fontSize: 11,
              }}
            >
              {shortHash(view.commitment)}
            </span>
          </div>
        </div>
      </div>

      <div className="today-columns">
        <div
          style={{
            background: "var(--color-surface)",
            borderRadius: "var(--radius-md)",
            padding: 14,
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
            }}
          >
            <Kicker>Sketch</Kicker>
            <PaletteRow colorIndex={colorIndex} onPick={setColorIndex} />
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              {doc.strokes.length} strokes
            </span>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canUndo(history)}
              onClick={() => {
                setHistory((h) => undo(h));
                setSelection(new Set());
                setRelationFirst("");
                setRelationSecond("");
              }}
            >
              Undo
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canRedo(history)}
              onClick={() => {
                setHistory((h) => redo(h));
                setSelection(new Set());
                setRelationFirst("");
                setRelationSecond("");
              }}
            >
              Redo
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={doc.strokes.length === 0}
              onClick={() => {
                commit(clearSketch(doc));
                setSelection(new Set());
                setRelationFirst("");
                setRelationSecond("");
              }}
            >
              Clear
            </button>
          </div>
          <SketchCanvas
            doc={doc}
            selection={selection}
            mode={mode}
            colorIndex={colorIndex}
            onCommitStroke={onCommitStroke}
            onPickStroke={onPickStroke}
            disabled={send.isPending}
          />
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            {sketchHint}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card">
            <Kicker>Impressions</Kicker>
            <input
              className="input"
              placeholder="one impression — Enter commits"
              value={impressionInput}
              onChange={(event) => setImpressionInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing) {
                  return;
                }
                if (event.key === "Enter") {
                  event.preventDefault();
                  addImpression();
                }
              }}
            />
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {impressions.map((text, index) => (
                <div
                  key={`${text}-${
                    // biome-ignore lint/suspicious/noArrayIndexKey: duplicates allowed
                    index
                  }`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 13,
                    padding: "6px 8px",
                    background: "var(--color-neutral-900)",
                    borderRadius: 6,
                  }}
                >
                  <span
                    style={{
                      width: 5,
                      height: 5,
                      borderRadius: "50%",
                      background: "var(--color-accent)",
                      flex: "none",
                    }}
                  />
                  <span style={{ flex: 1 }}>{text}</span>
                  <button
                    type="button"
                    title="remove"
                    aria-label={`remove impression ${text}`}
                    onClick={() =>
                      setImpressions((rows) =>
                        rows.filter((_, at) => at !== index),
                      )
                    }
                    style={{
                      border: "none",
                      background: "none",
                      color: "var(--color-neutral-500)",
                      cursor: "pointer",
                      fontSize: 14,
                      padding: "0 2px",
                    }}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <Kicker>Groups on the sketch</Kicker>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                type="button"
                className={
                  mode === "select" ? "btn btn-primary" : "btn btn-secondary"
                }
                onClick={() => {
                  setMode((old) => (old === "select" ? "draw" : "select"));
                  setSelection(new Set());
                }}
              >
                {mode === "select" ? "Done selecting" : "Select strokes"}
              </button>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                className="input"
                placeholder="what is it? e.g. tower"
                value={groupLabel}
                onChange={(event) => setGroupLabel(event.target.value)}
                style={{ flex: 1 }}
              />
              <button
                type="button"
                className="btn btn-primary"
                disabled={selection.size === 0 || groupLabel.trim() === ""}
                onClick={makeGroupNow}
              >
                Group
              </button>
            </div>
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 6,
                fontSize: 13,
              }}
            >
              {doc.groups.map((group, index) => (
                <div
                  key={group.id}
                  style={{ display: "flex", alignItems: "center", gap: 8 }}
                >
                  <span
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 3,
                      background: groupDisplay(index),
                    }}
                  />
                  {group.label}{" "}
                  <span
                    style={{ color: "var(--color-neutral-600)", fontSize: 11 }}
                  >
                    {group.id} ·{" "}
                    {
                      doc.strokes.filter(
                        (stroke) => doc.assignments[stroke.id] === group.id,
                      ).length
                    }{" "}
                    strokes
                  </span>
                </div>
              ))}
            </div>
            <div className="hr" style={{ margin: 0 }} />
            <Kicker>How things sit</Kicker>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr auto",
                gap: 6,
              }}
            >
              <select
                className="input"
                aria-label="first group"
                disabled={doc.groups.length < 2}
                value={relationFirst}
                onChange={(event) => setRelationFirst(event.target.value)}
                style={{ minHeight: 32, padding: "4px 6px", fontSize: 12 }}
              >
                <option value="">first…</option>
                {doc.groups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {groupName(group.id)}
                  </option>
                ))}
              </select>
              <select
                className="input"
                aria-label="relation"
                disabled={doc.groups.length < 2}
                value={relationName}
                onChange={(event) => setRelationName(event.target.value)}
                style={{ minHeight: 32, padding: "4px 6px", fontSize: 12 }}
              >
                {view.relation_vocabulary.map((name) => (
                  <option key={name} value={name}>
                    {wordingOf(name)}
                  </option>
                ))}
              </select>
              <select
                className="input"
                aria-label="second group"
                disabled={doc.groups.length < 2}
                value={relationSecond}
                onChange={(event) => setRelationSecond(event.target.value)}
                style={{ minHeight: 32, padding: "4px 6px", fontSize: 12 }}
              >
                <option value="">second…</option>
                {doc.groups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {groupName(group.id)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="btn btn-ghost"
                disabled={
                  doc.groups.length < 2 ||
                  relationFirst === "" ||
                  relationSecond === "" ||
                  relationFirst === relationSecond ||
                  !groupExists(relationFirst) ||
                  !groupExists(relationSecond)
                }
                onClick={addRelationNow}
              >
                Add
              </button>
            </div>
            {doc.relations.map((relation, index) => (
              <div
                key={`${relation.relation}-${relation.of[0]}-${relation.of[1]}-${
                  // biome-ignore lint/suspicious/noArrayIndexKey: duplicates allowed
                  index
                }`}
                style={{
                  fontSize: 13,
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span style={{ color: "var(--color-accent-300)" }}>
                  {groupName(relation.of[0])} {wordingOf(relation.relation)}{" "}
                  {groupName(relation.of[1])}
                </span>
                <button
                  type="button"
                  title="remove"
                  aria-label="remove relation"
                  onClick={() => commit(removeRelation(doc, index))}
                  style={{
                    border: "none",
                    background: "none",
                    color: "var(--color-neutral-500)",
                    cursor: "pointer",
                    fontSize: 14,
                    padding: "0 2px",
                  }}
                >
                  ×
                </button>
              </div>
            ))}
          </div>

          <div className="card">
            <Kicker>Notes</Kicker>
            <textarea
              className="input"
              placeholder="optional pasted notes"
              value={pastedText}
              onChange={(event) => setPastedText(event.target.value)}
              style={{ minHeight: 64 }}
            />
          </div>

          <div className="card elev-sm">
            <div style={{ fontSize: 13, color: "var(--color-neutral-400)" }}>
              {summary}
            </div>
            <button
              type="button"
              className="btn btn-primary btn-block"
              style={{ minHeight: 44 }}
              disabled={!scoreable || send.isPending}
              onClick={() => {
                if (sendingRef.current) {
                  return;
                }
                sendingRef.current = true;
                send.mutate(serialize(doc, impressions, pastedText));
              }}
            >
              {send.isPending ? "Sending…" : "Send today's trial"}
            </button>
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              {scoreable
                ? "One send per day — it locks when it lands."
                : "Add an impression, strokes, or pasted notes first."}
              {draftSaved ? " · draft saved" : ""}
            </div>
            {send.isError && !sent ? (
              <div style={{ fontSize: 13, color: "#bf616a" }} role="alert">
                {friendlyMessage(send.error)}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function ClosesIn(props: { closesAt: string }): React.JSX.Element | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    // A fixed one-minute tick: content-independent cadence (§8).
    const timer = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(timer);
  }, []);
  const remainingMs = Date.parse(props.closesAt) - now;
  if (Number.isNaN(remainingMs) || remainingMs <= 0) {
    return null;
  }
  const hours = Math.floor(remainingMs / 3_600_000);
  const minutes = Math.floor((remainingMs % 3_600_000) / 60_000);
  return (
    <span style={{ fontSize: 13, color: "var(--color-neutral-500)" }}>
      closes in {hours}h {minutes}m
    </span>
  );
}
