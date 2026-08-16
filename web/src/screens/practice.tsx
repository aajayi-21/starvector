/**
 * The practice screen (mock 1e, spec W1 B7): replay a revealed day
 * with its own sketch document — nothing is shared with the daily
 * draft and nothing is stored. The session counter is ephemeral by
 * design.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { useApi } from "../api/client";
import type { PracticeScore } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { SketchCanvas } from "../sketch/canvas";
import type { DocHistory, Point } from "../sketch/core";
import {
  addStroke,
  canRedo,
  canUndo,
  clearSketch,
  current,
  EMPTY_DOC,
  historyOf,
  pushDoc,
  redo,
  serialize,
  undo,
} from "../sketch/core";
import { Kicker } from "../ui/kicker";
import { PaletteRow } from "../ui/palette-row";

const EMPTY_SELECTION: ReadonlySet<number> = new Set<number>();

export function PracticeScreen(): React.JSX.Element {
  const api = useApi();
  const days = useQuery({
    queryKey: ["practice-days"],
    queryFn: () => api.getPracticeDays(),
  });

  if (days.isPending) {
    return (
      <div style={{ padding: 28 }}>
        <p className="text-muted">Loading…</p>
      </div>
    );
  }
  if (days.isError || days.data === undefined) {
    return (
      <div style={{ padding: 28, maxWidth: 520 }}>
        <div className="card">
          <span className="card-kicker">Practice</span>
          {isRefusal(days.error) ? (
            <p className="text-muted">
              No revealed day yet — play and reveal a day first.
            </p>
          ) : (
            <p className="text-muted" role="alert">
              {friendlyMessage(days.error)}
            </p>
          )}
        </div>
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
  const [colorIndex, setColorIndex] = useState(0);
  const [rounds, setRounds] = useState(0);
  const [result, setResult] = useState<PracticeScore | null>(null);
  const nextStrokeId = useRef(1);

  const doc = current(history);

  // The same in-flight ref lock as the daily send: isPending flips
  // a task late, and two score POSTs would double-count the session.
  const scoringRef = useRef(false);
  const score = useMutation({
    mutationFn: () => api.scorePractice(day, serialize(doc, [], "")),
    onSuccess: (answer) => {
      setResult(answer);
      setRounds((count) => count + 1);
    },
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

  const pickRandom = () => {
    const index = Math.floor(Math.random() * props.days.length);
    const picked = props.days[index];
    if (picked !== undefined) {
      setDay(picked.day);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "22px 28px 6px",
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            fontSize: 11,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--color-accent)",
            marginRight: 8,
          }}
        >
          Practice
        </div>
        <select
          className="input"
          aria-label="practice day"
          style={{ width: "auto" }}
          value={day}
          onChange={(event) => setDay(event.target.value)}
        >
          {props.days.map((row) => (
            <option key={row.day} value={row.day}>
              {row.day} · {row.trial_code}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={pickRandom}
        >
          Random day
        </button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
          Nothing is stored — practice never touches the skill number.
        </span>
      </div>

      <div className="today-columns" style={{ paddingTop: 14 }}>
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
          </div>
          <SketchCanvas
            doc={doc}
            selection={EMPTY_SELECTION}
            mode="draw"
            colorIndex={colorIndex}
            onCommitStroke={onCommitStroke}
            onPickStroke={() => undefined}
            disabled={score.isPending}
          />
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canUndo(history)}
              onClick={() => setHistory((h) => undo(h))}
            >
              Undo
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!canRedo(history)}
              onClick={() => setHistory((h) => redo(h))}
            >
              Redo
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={doc.strokes.length === 0}
              onClick={() =>
                setHistory((h) => pushDoc(h, clearSketch(current(h))))
              }
            >
              Clear
            </button>
            <span style={{ flex: 1 }} />
            <button
              type="button"
              className="btn btn-primary"
              style={{ minHeight: 40 }}
              disabled={
                doc.strokes.length === 0 || score.isPending || day === ""
              }
              onClick={() => {
                if (scoringRef.current) {
                  return;
                }
                scoringRef.current = true;
                score.mutate();
              }}
            >
              {score.isPending ? "Scoring…" : "Score now"}
            </button>
          </div>
          {score.isError ? (
            <div style={{ fontSize: 13, color: "#bf616a" }} role="alert">
              {friendlyMessage(score.error)}
            </div>
          ) : null}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {result === null ? (
            <div className="card">
              <Kicker>Practice score</Kicker>
              <p className="text-muted" style={{ fontSize: 13 }}>
                Draw, then Score now. The revealed target and the match report
                appear here.
              </p>
            </div>
          ) : (
            <>
              <div className="card elev-sm" style={{ gap: 8 }}>
                <Kicker>Practice score</Kicker>
                <div
                  style={{
                    fontSize: 44,
                    lineHeight: 1,
                    fontWeight: 500,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {result.trial.p.toFixed(4)}
                </div>
                <div
                  style={{ fontSize: 13, color: "var(--color-neutral-400)" }}
                >
                  beat {result.trial.beaten} of {result.trial.decoy_count}{" "}
                  decoys · rank {result.trial.target_rank} · position{" "}
                  {result.target_position} of the full ordering
                </div>
                <div
                  style={{ fontSize: 12, color: "var(--color-neutral-500)" }}
                >
                  {rounds} scored this session
                </div>
              </div>
              <div className="card" style={{ gap: 8 }}>
                <Kicker>Revealed target</Kicker>
                <img
                  className="lighten"
                  src={api.imageUrl(result.target_id)}
                  alt={`revealed practice target for ${result.day}`}
                  style={{
                    width: "100%",
                    aspectRatio: "1 / 1",
                    borderRadius: 8,
                  }}
                />
              </div>
              {result.report.length === 0 ? null : (
                <div className="card" style={{ gap: 8 }}>
                  <Kicker>What matched</Kicker>
                  <table className="table" style={{ fontSize: 13 }}>
                    <thead>
                      <tr>
                        <th>atom</th>
                        <th>element</th>
                        <th>sim</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.report.map((row) => (
                        <tr key={row.atom_id}>
                          <td>{row.atom_text}</td>
                          <td>{row.element ?? "-"}</td>
                          <td>{row.similarity.toFixed(3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
