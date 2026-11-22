/**
 * Practice (mock 1e, spec W1 B7, grown by spec A1 §6; copy per spec
 * BR1 §6; the Studio design of 2026-11-21): the Practice view of the
 * Play place. A step back from today in the row of days
 * (ui/day-stepper.tsx) is practice on that day's photo, and the path
 * holds the day: `/practice?day=…`. Replay a revealed day with its own
 * sketch — nothing is shared with today's draft and nothing is stored.
 * The same canvas and word inputs as today; the head of the side holds
 * the days and the day's code. After a check, the photo and the result
 * take the side, beside the sketch; the player goes back to edit or
 * starts over. The draft saves on this device with its own key (spec
 * PL1 §8), and a word typed and not added goes in with the check.
 */

import { Plus } from "@phosphor-icons/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
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
import { useDayNames } from "../ui/day-names";
import { DayStepper } from "../ui/day-stepper";
import { ordinal, percentBeaten } from "../ui/format";
import { PlayFrame, PlayHow, PlayMessage } from "../ui/play-switch";
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
      <PlayMessage title="Practice" view="practice">
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
  const navigate = useNavigate();
  const search = useSearch({ from: "/practice" });
  const [restored] = useState(() => readPracticeDraft());
  // The day is the one in the path. With none there, or one that is not
  // a practice day, it is the day of the draft on this device, and then
  // the newest day.
  const has = (label: string | undefined): label is string =>
    label !== undefined && props.days.some((row) => row.day === label);
  const day = has(search.day)
    ? search.day
    : has(restored?.day)
      ? restored.day
      : (props.days[0]?.day ?? "");
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

  // A result is the result of one day: a new day clears it. The sketch
  // stays, as it did when the day came from a list.
  const shownDay = useRef(day);
  useEffect(() => {
    if (shownDay.current !== day) {
      shownDay.current = day;
      setResult(null);
    }
  }, [day]);

  // The path names the day, so a reload and the row of days agree.
  useEffect(() => {
    if (day !== "" && search.day !== day) {
      void navigate({ to: "/practice", search: { day }, replace: true });
    }
  }, [day, search.day, navigate]);

  // Closing the part while lines are picked gives the pen back.
  const [labelOpen, setLabelOpen] = useState(false);
  const toggleLabel = (): void => {
    if (labelOpen && mode === "select") {
      setMode("draw");
      setSelection(new Set());
    }
    setLabelOpen((old) => !old);
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
      <section className="play-day" aria-label="Practice day">
        <DayStepper view="practice" day={day === "" ? null : day} />
        <DayCode
          code={props.days.find((row) => row.day === day)?.trial_code ?? ""}
        />
        <div className="play-day-meta">
          <p className="muted">
            This day is over. Nothing here is saved or counted.
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
        disabled={score.isPending || result !== null}
        hint={
          result !== null
            ? "Choose “Edit and check again” to keep drawing."
            : mode === "select"
              ? "Tap the lines that belong together."
              : ""
        }
        emptyNote="Sketch and describe what comes to mind for this code, then see the photo."
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
              <div className="send-bar-after">
                <p className="subtle tiny send-bar-hint">
                  See the photo and how close you came. You can try many times,
                  up to an hourly limit. Your draft is saved on this device.
                </p>
                <PlayHow />
                {score.isError ? (
                  <div className="notice notice-bad" role="alert">
                    {friendlyMessage(score.error)}
                  </div>
                ) : null}
              </div>
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
  const names = useDayNames();
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
              `Hidden target of ${names.long(result.day)}`
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
