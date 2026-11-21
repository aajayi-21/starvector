/**
 * Practice (mock 1e, spec W1 B7, grown by spec A1 §6; layout and
 * copy per spec BR1 §6): the Practice view of the Play place, under
 * the switch it shares with today's sketch (ui/play-switch.tsx).
 * Replay a revealed day with its own sketch — nothing is shared with
 * today's draft and nothing is stored. The same three columns, canvas,
 * and word inputs as today; the first column holds the day's code and
 * the day picker. After a check, the photo and the result take the
 * third column, level with the sketch; the player goes back to edit or
 * starts over. The draft saves on this device with its own key (spec
 * PL1 §8), and a word typed and not added goes in with the check.
 */

import { CaretRight } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { useApi } from "../api/client";
import type { PracticeScore } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { CanvasPanel } from "../intake/canvas-panel";
import {
  clearPracticeDraft,
  hasContent,
  readPracticeDraft,
  writePracticeDraft,
} from "../intake/drafts";
import { GroupControls } from "../intake/groups-card";
import { ImpressionsCard } from "../intake/impressions-card";
import { sendBlock, sendBlockHint } from "../intake/send-gate";
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
import { formatDay, ordinal, percentBeaten } from "../ui/format";
import { PlayFrame, PlayMessage } from "../ui/play-switch";
import { Credit, WordMatches } from "./reveal";

export function PracticeScreen(): React.JSX.Element {
  return (
    <PlayFrame>
      <PracticeView />
    </PlayFrame>
  );
}

function PracticeView(): React.JSX.Element {
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
      <PlayMessage title="Practice">
        {isRefusal(days.error) ? (
          <p className="muted">
            Practice uses photos from days that are over. The first one appears
            after the first day closes.
          </p>
        ) : (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(days.error)}
          </div>
        )}
      </PlayMessage>
    );
  }
  return (
    <PracticeWorkspace
      days={days.data.days}
      minStrokes={days.data.min_strokes}
    />
  );
}

function PracticeWorkspace(props: {
  days: ReadonlyArray<{ day: string; trial_code: string }>;
  minStrokes: number;
}): React.JSX.Element {
  const api = useApi();
  const [restored] = useState(() => readPracticeDraft());
  const [day, setDay] = useState(() =>
    restored !== null && props.days.some((row) => row.day === restored.day)
      ? restored.day
      : (props.days[0]?.day ?? ""),
  );
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
  const [result, setResult] = useState<PracticeScore | null>(null);
  const nextStrokeId = useRef(restored?.nextStrokeId ?? 1);

  const doc = current(history);
  const commit = (next: SketchDoc) => setHistory((h) => pushDoc(h, next));

  // The same in-flight ref lock as the daily send: isPending flips
  // a task late, and two score POSTs would race.
  const scoringRef = useRef(false);
  const score = useMutation({
    mutationFn: (words: string[]) =>
      api.scorePractice(day, serialize(doc, words, "")),
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

  // Saved as it changes: practice stores nothing on the server, and a
  // draft on this device is the only copy.
  useEffect(() => {
    const timer = setTimeout(() => {
      const draft = {
        day,
        doc,
        impressions,
        typedWord,
        nextStrokeId: nextStrokeId.current,
      };
      if (hasContent(draft)) {
        writePracticeDraft(draft);
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [day, doc, impressions, typedWord]);

  // The mirror of the server's refusals: no-scoreable-atom, min-strokes.
  const typed = typedWord.trim();
  const block = sendBlock(
    doc.strokes.length,
    impressions.length > 0 || typed !== "",
    props.minStrokes,
  );
  const scoreable = block === null;

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
    setTypedWord("");
    setSelection(new Set());
    setMode("draw");
    setResult(null);
    clearPracticeDraft();
  };

  return (
    <div className={result === null ? "workspace" : "workspace has-result"}>
      <section className="play-brief" aria-label="Practice day">
        <p className="subtle small play-brief-label">This day's code</p>
        <DayCode
          code={props.days.find((row) => row.day === day)?.trial_code ?? ""}
        />
        <div className="field practice-day">
          <label className="label" htmlFor="practice-day">
            Photo from
          </label>
          <select
            id="practice-day"
            className="input"
            value={day}
            onChange={(event) => pickDay(event.target.value)}
          >
            {props.days.map((row) => (
              <option key={row.day} value={row.day}>
                {formatDay(row.day)}
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          className="btn btn-secondary practice-surprise"
          onClick={surprise}
        >
          Surprise me
        </button>
        <hr className="divider play-brief-rule" />
        <p className="play-brief-lead">
          This day is over. Sketch and describe what comes to mind for its code,
          then see the photo.
        </p>
        <p className="muted small play-brief-note">
          Nothing here is saved or counted.
        </p>
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
        disabled={score.isPending || result !== null}
        hint={
          result !== null
            ? "Choose “Edit and check again” to keep drawing."
            : mode === "select"
              ? "Tap the lines that belong together."
              : ""
        }
      />

      <aside className="side-cell" aria-label="Practice">
        {result === null ? (
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
                    <span className="row-meta">
                      Optional
                      <CaretRight
                        size={16}
                        aria-hidden="true"
                        className="row-chevron"
                      />
                    </span>
                  </summary>
                  <div className="row-body">
                    <GroupControls
                      doc={doc}
                      mode={mode}
                      selectionSize={selection.size}
                      onToggleSelect={() => {
                        setMode((old) =>
                          old === "select" ? "draw" : "select",
                        );
                        setSelection(new Set());
                      }}
                      onMakeGroup={makeGroupWith}
                    />
                  </div>
                </details>
              </div>
            </div>
            <section className="action-bar send-bar" aria-label="Check">
              {scoreable ? null : (
                <p className="send-bar-facts">
                  <span className="send-bar-note">
                    {sendBlockHint(block, props.minStrokes)}
                  </span>
                </p>
              )}
              <button
                type="button"
                className="btn btn-primary btn-large btn-block send-bar-buttons"
                disabled={!scoreable || score.isPending || day === ""}
                onClick={() => {
                  if (scoringRef.current) {
                    return;
                  }
                  scoringRef.current = true;
                  // A typed word counts: the player can see it on the
                  // screen, and nothing here is final.
                  const words =
                    typed === "" ? impressions : [...impressions, typed];
                  setImpressions(words);
                  setTypedWord("");
                  score.mutate(words);
                }}
              >
                {score.isPending ? "Checking…" : "Check my practice"}
              </button>
              <p className="subtle tiny send-bar-hint">
                See the photo and how close you came. You can try many times, up
                to an hourly limit. Your draft is saved on this device.
              </p>
              {score.isError ? (
                <div className="notice notice-bad" role="alert">
                  {friendlyMessage(score.error)}
                </div>
              ) : null}
            </section>
          </div>
        ) : (
          <PracticeResult
            result={result}
            onEdit={() => setResult(null)}
            onStartOver={startOver}
          />
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

function PracticeResult(props: {
  result: PracticeScore;
  onEdit: () => void;
  onStartOver: () => void;
}): React.JSX.Element {
  const api = useApi();
  const { result } = props;
  const trial = result.trial;
  return (
    <div className="practice-result">
      <div className="practice-photo">
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
      </div>
      <section className="practice-score" aria-label="Practice result">
        <h2 className="practice-score-label">Practice result</h2>
        <div className="figure practice-number">{percentBeaten(trial.p)}%</div>
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
        <Link to="/reveal" search={{ day: result.day }}>
          See everyone's results for this day
        </Link>
      </section>
    </div>
  );
}
