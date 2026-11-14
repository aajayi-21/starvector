/**
 * The roster and the player history (spec A1 §5, grown by spec BR1
 * §7.4).
 *
 * Each row counts the player's signed-in devices, their last sign-in,
 * and their sends. Clicking a player opens their account (devices,
 * access controls) and their full history: each stored day with the
 * sent flag and the stored trial row. Clicking a day row opens that
 * player's stored submission through the standing SubmissionView,
 * and "Score and rank" serves their record through the grown rankings
 * read. The day browser keeps its shape — this panel is the second
 * axis, by player rather than by day.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { DevApi } from "./api";
import { DevApiError } from "./api";
import {
  ConfirmAction,
  ErrorNote,
  refusedRead,
  SHOWS_TARGET,
  StatusBadge,
} from "./controls";
import { utcShort } from "./format";
import { PlayerAccount } from "./player-account";
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
      setNote("");
    } catch (error) {
      setPlayers([]);
      // The same wording rule as the day browser: a refused
      // operator check reads as no --dev flag, on purpose.
      setNote(refusedRead(error));
    }
  }, [api]);

  useEffect(() => {
    // `reload` re-fires this effect when the token field blurs;
    // the fetch itself does not read it.
    void reload;
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

  // A ranking of an open day shows the target, so it asks first.
  const openedStatus = history?.days.find(
    (row) => row.day === openedDay,
  )?.status;

  // The world of spec M1 ruling 7: no record, one synthetic row.
  const noAccounts =
    players !== null &&
    players.length === 1 &&
    players[0]?.status === "configured";

  return (
    <div className="card" id="roster-panel">
      <div className="eyebrow">Players</div>
      {players === null ? (
        <p className="subtle small" role="status">
          loading…
        </p>
      ) : noAccounts ? (
        <div className="notice" role="note">
          Nobody has an account on this server yet. A player makes their own
          account on the app's sign-in page when the server config has sign-up
          open. Until an account is stored, everyone who opens the app plays as{" "}
          {players[0]?.player} with no sign-in.
        </div>
      ) : (
        <div className="dev-scroll-x">
          <table className="table dev-table">
            <thead>
              <tr>
                <th>player</th>
                <th>status</th>
                <th className="num">devices</th>
                <th>last sign-in (UTC)</th>
                <th className="num">sends</th>
                <th>created (UTC)</th>
                <th>
                  <span className="visually-hidden">action</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {players.map((row) => (
                <tr
                  key={row.player}
                  className={row.player === selected ? "dev-picked" : undefined}
                >
                  <td>
                    <button
                      type="button"
                      className="dev-link-button"
                      aria-pressed={row.player === selected}
                      onClick={() => void showPlayer(row.player)}
                    >
                      {row.player}
                    </button>
                    {row.display_name === row.player ? null : (
                      <span className="subtle"> {row.display_name}</span>
                    )}
                  </td>
                  <td>
                    <StatusBadge status={row.status} />
                  </td>
                  <td className="num">
                    {row.devices}
                    {row.device_codes > 0 ? (
                      <span className="subtle" title="device codes that wait">
                        {" "}
                        +{row.device_codes} code
                      </span>
                    ) : null}
                  </td>
                  <td>{utcShort(row.last_signed_in)}</td>
                  <td className="num">{row.sends}</td>
                  <td>{utcShort(row.created_at)}</td>
                  <td className="num">
                    <button
                      type="button"
                      className="btn btn-secondary dev-small-button"
                      aria-label={`Manage ${row.player}`}
                      onClick={() => void showPlayer(row.player)}
                    >
                      Manage
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorNote text={note} />

      {selected === null || noAccounts ? null : (
        <>
          <hr className="divider" />
          <PlayerAccount
            key={selected}
            api={api}
            player={selected}
            onChanged={() => void loadPlayers()}
          />
          <div className="dev-subhead">{selected} — history</div>
          {history === null ? (
            <p className="subtle small" role="status">
              loading…
            </p>
          ) : history.days.length === 0 ? (
            <p className="subtle small">no stored day yet</p>
          ) : (
            <table className="table dev-table">
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
                    className={row.day === openedDay ? "dev-picked" : undefined}
                  >
                    <td>
                      <button
                        type="button"
                        className="dev-link-button"
                        aria-pressed={row.day === openedDay}
                        onClick={() => void showDay(row)}
                      >
                        {row.day}
                      </button>
                    </td>
                    <td className="dev-mono">{row.trial_code}</td>
                    <td>{row.status}</td>
                    <td>{row.submitted ? "sent" : "—"}</td>
                    <td className="num">
                      {row.trial === null ? "—" : row.trial.p.toFixed(4)}
                    </td>
                    <td className="num">
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
        <p className="subtle small" role="status">
          {dayNote === "" ? "loading…" : dayNote}
        </p>
      ) : (
        <>
          <SubmissionView stored={stored} />
          <div className="dev-row">
            {rankings === null ? (
              openedStatus === "open" ? (
                <ConfirmAction
                  label="Score and rank the submission"
                  question={SHOWS_TARGET}
                  confirmLabel="Yes, show the target"
                  variant="secondary"
                  onConfirm={() => void loadRankings()}
                />
              ) : (
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => void loadRankings()}
                >
                  Score and rank the submission
                </button>
              )
            ) : null}
            <span className="subtle small">
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
