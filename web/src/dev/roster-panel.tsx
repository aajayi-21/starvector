/**
 * The roster and the player history (spec A1 §5).
 *
 * Clicking a player opens their full history: each stored day with
 * the sent flag and the stored trial row. Clicking a day row opens
 * that player's stored submission through the standing
 * SubmissionView, and "Score and rank" serves their record through
 * the grown rankings read. The day browser keeps its shape — this
 * panel is the second axis, by player rather than by day.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { DevApi } from "./api";
import { DevApiError } from "./api";
import { RankingsView } from "./rankings";
import { SubmissionView } from "./submission-view";
import type {
  DevHistory,
  DevHistoryDay,
  DevRankings,
  DevRosterRow,
  DevStored,
} from "./types";

function messageOf(error: unknown): string {
  return error instanceof DevApiError ? error.message : "refused";
}

export function RosterPanel(props: {
  api: DevApi;
  /** Bumped by the console when the operator token changes, so a
   * roster that failed before the paste loads without a reload. */
  reload?: number;
}): React.JSX.Element {
  const { api, reload } = props;
  const [players, setPlayers] = useState<DevRosterRow[] | null>(null);
  const [note, setNote] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<DevHistory | null>(null);
  const [openedDay, setOpenedDay] = useState<string | null>(null);
  const [stored, setStored] = useState<DevStored | null>(null);
  const [dayNote, setDayNote] = useState("");
  const [rankings, setRankings] = useState<DevRankings | null>(null);
  const [rankNote, setRankNote] = useState("");
  // Each switch takes the next token; a stale response belongs to
  // a player or day the operator left and is dropped.
  const switchToken = useRef(0);

  const loadPlayers = useCallback(async () => {
    try {
      const roster = await api.getPlayers();
      setPlayers(roster.players);
      setNote(roster.players.length === 0 ? "no players yet" : "");
    } catch (error) {
      setPlayers([]);
      // The same wording rule as the day browser: a refused
      // operator check reads as no --dev flag, on purpose.
      setNote(
        error instanceof DevApiError && error.status === 404
          ? "not found: start the server with --dev, or the operator " +
              "token is missing or wrong"
          : messageOf(error),
      );
    }
  }, [api]);

  useEffect(() => {
    void loadPlayers();
  }, [loadPlayers, reload]);

  const showPlayer = async (name: string) => {
    switchToken.current += 1;
    const token = switchToken.current;
    setSelected(name);
    setHistory(null);
    setOpenedDay(null);
    setStored(null);
    setRankings(null);
    setDayNote("");
    setRankNote("");
    try {
      const answer = await api.getHistory(name);
      if (token === switchToken.current) {
        setHistory(answer);
      }
    } catch (error) {
      if (token === switchToken.current) {
        setNote(messageOf(error));
      }
    }
  };

  const showDay = async (row: DevHistoryDay) => {
    if (selected === null) {
      return;
    }
    switchToken.current += 1;
    const token = switchToken.current;
    const fresh = () => token === switchToken.current;
    setOpenedDay(row.day);
    setStored(null);
    setRankings(null);
    setDayNote("");
    setRankNote("");
    try {
      const document = await api.getSubmission(row.day, selected);
      if (fresh()) {
        setStored(document);
      }
    } catch (error) {
      if (!fresh()) {
        return;
      }
      setDayNote(
        error instanceof DevApiError && error.status === 404
          ? "nothing sent this day"
          : messageOf(error),
      );
    }
  };

  const loadRankings = async () => {
    if (selected === null || openedDay === null) {
      return;
    }
    // The same staleness guard as showPlayer and showDay: scoring
    // is slow, and a response from a player or day the operator
    // left must not render under the one they moved to.
    const token = switchToken.current;
    const fresh = () => token === switchToken.current;
    setRankNote("scoring…");
    try {
      const answer = await api.getRankings(openedDay, selected);
      if (!fresh()) {
        return;
      }
      setRankings(answer);
      setRankNote("");
    } catch (error) {
      if (fresh()) {
        setRankNote(messageOf(error));
      }
    }
  };

  return (
    <div className="card" style={{ gap: 10 }} id="roster-panel">
      <span className="card-kicker">Players</span>
      {players === null ? (
        <p className="text-muted" style={{ fontSize: 13 }} role="status">
          loading…
        </p>
      ) : (
        <table className="table" style={{ fontSize: 13 }}>
          <thead>
            <tr>
              <th>player</th>
              <th>label</th>
              <th>status</th>
              <th>created</th>
            </tr>
          </thead>
          <tbody>
            {players.map((row) => (
              <tr
                key={row.player}
                style={
                  row.player === selected
                    ? { color: "var(--color-accent-300)" }
                    : undefined
                }
              >
                <td>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    style={{ padding: "2px 8px" }}
                    onClick={() => void showPlayer(row.player)}
                  >
                    {row.player}
                  </button>
                </td>
                <td>{row.display_name}</td>
                <td>{row.status}</td>
                <td>{row.created_at ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {note === "" ? null : (
        <p className="text-muted" role="status" style={{ margin: 0 }}>
          {note}
        </p>
      )}

      {selected === null ? null : (
        <>
          <div className="hr" style={{ margin: 0 }} />
          <span className="card-kicker">{selected} — history</span>
          {history === null ? (
            <p className="text-muted" style={{ fontSize: 13 }} role="status">
              loading…
            </p>
          ) : history.days.length === 0 ? (
            <p className="text-muted" style={{ fontSize: 13 }}>
              no stored day yet
            </p>
          ) : (
            <table className="table" style={{ fontSize: 13 }}>
              <thead>
                <tr>
                  <th>day</th>
                  <th>code</th>
                  <th>status</th>
                  <th>sent</th>
                  <th>score</th>
                  <th>rank</th>
                </tr>
              </thead>
              <tbody>
                {history.days.map((row) => (
                  <tr
                    key={row.day}
                    style={
                      row.day === openedDay
                        ? { color: "var(--color-accent-300)" }
                        : undefined
                    }
                  >
                    <td>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        style={{ padding: "2px 8px" }}
                        onClick={() => void showDay(row)}
                      >
                        {row.day}
                      </button>
                    </td>
                    <td
                      style={{
                        fontFamily: "ui-monospace, Menlo, monospace",
                      }}
                    >
                      {row.trial_code}
                    </td>
                    <td>{row.status}</td>
                    <td>{row.submitted ? "sent" : "—"}</td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>
                      {row.trial === null ? "—" : row.trial.p.toFixed(4)}
                    </td>
                    <td style={{ fontVariantNumeric: "tabular-nums" }}>
                      {row.trial === null
                        ? "—"
                        : `${row.trial.target_rank} of ${
                            row.trial.decoy_count + 1
                          }`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}

      {openedDay === null ? null : stored === null ? (
        <p className="text-muted" style={{ fontSize: 13 }} role="status">
          {dayNote === "" ? "loading…" : dayNote}
        </p>
      ) : (
        <>
          <SubmissionView stored={stored} />
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {rankings === null ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void loadRankings()}
              >
                Score and rank the submission
              </button>
            ) : null}
            <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
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
    </div>
  );
}
