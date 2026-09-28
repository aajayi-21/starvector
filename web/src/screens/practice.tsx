/**
 * Practice (mock 1e, spec W1 B7, grown by spec A1 §6; layout and
 * copy per spec BR1 §6): replay a revealed day with its own sketch —
 * nothing is shared with today's draft and nothing is stored. The
 * same canvas and word inputs as today. After a check, the result
 * takes the right column; the player goes back to edit or starts
 * over.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useRef, useState } from "react";

import { useApi } from "../api/client";
import type { PracticeScore } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { CanvasPanel } from "../intake/canvas-panel";
import { GroupControls } from "../intake/groups-card";
import { ImpressionsCard } from "../intake/impressions-card";
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
import { formatDay, ordinal, percentBeaten } from "../ui/format";
import { Credit, WordMatches } from "./reveal";

export function PracticeScreen(): React.JSX.Element {
  const api = useApi();
  const days = useQuery({
    queryKey: ["practice-days"],
    queryFn: () => api.getPracticeDays(),
  });

  if (days.isPending) {
    return (
      <p className="subtle" aria-busy="true">
        Loading…
      </p>
    );
  }
  if (days.isError || days.data === undefined) {
    return (
      <div className="page-narrow" style={{ margin: "0 auto" }}>
        <section className="card card-hero">
          <h2>Practice</h2>
          {isRefusal(days.error) ? (
            <p className="muted">
              Practice uses photos from days that are over. The first one
              appears after the first day closes.
            </p>
          ) : (
            <div className="notice notice-bad" role="alert">
              {friendlyMessage(days.error)}
            </div>
          )}
        </section>
      </div>
    );
  }
  return <PracticeWorkspace days={days.data.days} />;
}

function PracticeWorkspace(props: {
  days: ReadonlyArray<{ day: string; trial_code: string }>;
}): React.JSX.Element {
  const api = useApi();
  const [day, setDay] = useState(() => props.days[0]?.day ?? "");
  const [history, setHistory] = useState<DocHistory>(() =>
    historyOf(EMPTY_DOC),
  );
  const [selection, setSelection] = useState<ReadonlySet<number>>(
    () => new Set<number>(),
  );
  const [mode, setMode] = useState<"draw" | "select">("draw");
  const [colorIndex, setColorIndex] = useState(0);
  const [impressions, setImpressions] = useState<string[]>([]);
  const [result, setResult] = useState<PracticeScore | null>(null);
  const nextStrokeId = useRef(1);

  const doc = current(history);
  const commit = (next: SketchDoc) => setHistory((h) => pushDoc(h, next));

  // The same in-flight ref lock as the daily send: isPending flips
  // a task late, and two score POSTs would race.
  const scoringRef = useRef(false);
  const score = useMutation({
    mutationFn: () => api.scorePractice(day, serialize(doc, impressions, "")),
    onSuccess: (answer) => setResult(answer),
    onSettled: () => {
      scoringRef.current = false;
    },
  });

  const onCommitStroke = (points: Point[]) => {
    const id = nextStrokeId.current;
    nextStrokeId.current += 1;
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

  const makeGroupWith = (label: string) => {
    if (label === "" || selection.size === 0) {
      return;
    }
    commit(makeGroup(doc, [...selection], label));
    setSelection(new Set());
    setMode("draw");
  };

  // The mirror of the server's no-scoreable-atom refusal.
  const scoreable = doc.strokes.length > 0 || impressions.length > 0;

  const pickDay = (next: string) => {
    setDay(next);
    setResult(null);
  };

  const surprise = () => {
    const index = Math.floor(Math.random() * props.days.length);
    const picked = props.days[index];
    if (picked !== undefined) {
      pickDay(picked.day);
    }
  };

  const startOver = () => {
    setHistory(historyOf(EMPTY_DOC));
    setImpressions([]);
    setSelection(new Set());
    setMode("draw");
    setResult(null);
  };

  return (
    <div className="stack-lg">
      <header className="row-between" style={{ alignItems: "flex-end" }}>
        <div className="stack-sm">
          <h1>Practice</h1>
          <p className="muted">
            Replay a past day's photo and see how you'd have done. Nothing here
            is saved or counted.
          </p>
        </div>
        <div className="row">
          <label className="label" htmlFor="practice-day">
            Photo from
          </label>
          <select
            id="practice-day"
            className="input"
            style={{ width: "auto" }}
            value={day}
            onChange={(event) => pickDay(event.target.value)}
          >
            {props.days.map((row) => (
              <option key={row.day} value={row.day}>
                {formatDay(row.day)} · {row.trial_code}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={surprise}
          >
            Surprise me
          </button>
        </div>
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
          disabled={score.isPending || result !== null}
          hint={
            result !== null
              ? "Choose “Edit and check again” to keep drawing."
              : mode === "select"
                ? "Tap the strokes that belong together."
                : "Draw whatever comes to mind for this day's code."
          }
        />

        <aside className="stack side-panel" aria-label="Practice">
          {result === null ? (
            <>
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
                </div>
              </details>
              <section className="card" aria-label="Check">
                <button
                  type="button"
                  className="btn btn-primary btn-large btn-block"
                  disabled={!scoreable || score.isPending || day === ""}
                  onClick={() => {
                    if (scoringRef.current) {
                      return;
                    }
                    scoringRef.current = true;
                    score.mutate();
                  }}
                >
                  {score.isPending ? "Checking…" : "Check my practice"}
                </button>
                <p className="hint">
                  {scoreable
                    ? "See the photo and how close you came. You can try as often as you like."
                    : "Draw something or add a word first."}
                </p>
                {score.isError ? (
                  <div className="notice notice-bad" role="alert">
                    {friendlyMessage(score.error)}
                  </div>
                ) : null}
              </section>
            </>
          ) : (
            <PracticeResult
              result={result}
              onEdit={() => setResult(null)}
              onStartOver={startOver}
            />
          )}
        </aside>
      </div>
      {result === null || result.report.length === 0 ? null : (
        <WordMatches rows={result.report} />
      )}
    </div>
  );
}

function PracticeResult(props: {
  result: PracticeScore;
  onEdit: () => void;
  onStartOver: () => void;
}): React.JSX.Element {
  const api = useApi();
  const { result } = props;
  const trial = result.trial;
  return (
    <>
      <section className="card card-hero" aria-label="Practice result">
        <div className="eyebrow">Practice result</div>
        <div className="big-number" style={{ fontSize: 52 }}>
          {percentBeaten(trial.p)}%
        </div>
        <p>
          Your sketch matched this photo better than {trial.beaten} of the other{" "}
          {trial.decoy_count} photos.
        </p>
        <ChanceMeter p={trial.p} />
        <p className="muted small">
          It was your {ordinal(trial.target_rank)}-closest match. Practice isn't
          saved and doesn't count.
        </p>
        <div className="row">
          <button
            type="button"
            className="btn btn-primary"
            onClick={props.onEdit}
          >
            Edit and check again
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={props.onStartOver}
          >
            Start over
          </button>
        </div>
      </section>
      <section className="card">
        <div className="picture-frame">
          <img
            src={api.imageUrl(result.target_id)}
            alt={
              result.credit?.title ??
              `Hidden target of ${formatDay(result.day)}`
            }
          />
        </div>
        <Credit credit={result.credit} />
        <Link to="/reveal" search={{ day: result.day }} className="small">
          See everyone's results for this day
        </Link>
      </section>
    </>
  );
}
