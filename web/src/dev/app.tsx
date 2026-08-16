/**
 * The operator console (spec S2 §5): the day browser with the
 * latest-day-only control rule, the blind-run target toggle, the
 * stored-submission viewer, and the rankings view. Reached locally
 * or through the SSH tunnel — the proxy answers 404 for it in
 * production.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { DevApi } from "./api";
import { DevApiError, makeDevApi } from "./api";
import { RankingsView } from "./rankings";
import { SubmissionView } from "./submission-view";
import type { DevDayRow, DevRankings, DevStored } from "./types";

function messageOf(error: unknown): string {
  return error instanceof DevApiError ? error.message : "refused";
}

export function DevApp(props: { api?: DevApi }): React.JSX.Element {
  const [api] = useState<DevApi>(() => props.api ?? makeDevApi());
  const [days, setDays] = useState<DevDayRow[] | null>(null);
  const [note, setNote] = useState("");
  const [selected, setSelected] = useState<DevDayRow | null>(null);
  const [targetShown, setTargetShown] = useState(false);
  const [stored, setStored] = useState<DevStored | null>(null);
  const [rankings, setRankings] = useState<DevRankings | null>(null);
  const [rankNote, setRankNote] = useState("");
  const [dayNote, setDayNote] = useState("");
  const [controlNote, setControlNote] = useState("");
  // Each day switch takes the next token; a response whose token is
  // stale belongs to a day the operator left and is dropped.
  const dayToken = useRef(0);

  const showDay = useCallback(
    async (row: DevDayRow) => {
      // A day switch clears the target state and the loaded data,
      // so switching days never leaks the new target.
      dayToken.current += 1;
      const token = dayToken.current;
      const fresh = () => token === dayToken.current;
      setSelected(row);
      setTargetShown(false);
      setStored(null);
      setRankings(null);
      setRankNote("");
      setDayNote("");
      try {
        const document = await api.getSubmission(row.day);
        if (!fresh()) {
          return;
        }
        setStored(document);
        if (row.status !== "open") {
          setRankNote("scoring…");
          const board = await api.getRankings(row.day);
          if (!fresh()) {
            return;
          }
          setRankings(board);
          setRankNote("");
        }
      } catch (error) {
        if (!fresh()) {
          return;
        }
        if (error instanceof DevApiError && error.status === 404) {
          setDayNote("nothing sent this day");
          return;
        }
        setDayNote(messageOf(error));
        setRankNote("");
      }
    },
    [api],
  );

  const loadDays = useCallback(async () => {
    try {
      const listing = await api.getDays();
      setDays(listing.days);
      setNote(listing.days.length === 0 ? "no day yet" : "");
      const first = listing.days[0];
      if (first !== undefined) {
        await showDay(first);
      } else {
        setSelected(null);
      }
    } catch (error) {
      setDays([]);
      setSelected(null);
      setNote(
        error instanceof DevApiError && error.status === 404
          ? "start the server with --dev to use this console"
          : messageOf(error),
      );
    }
  }, [api, showDay]);

  useEffect(() => {
    void loadDays();
  }, [loadDays]);

  const act = async (action: () => Promise<unknown>, confirmText?: string) => {
    if (confirmText !== undefined && !window.confirm(confirmText)) {
      return;
    }
    setControlNote("working…");
    try {
      await action();
      setControlNote("");
      await loadDays();
    } catch (error) {
      setControlNote(messageOf(error));
    }
  };

  const latestDay = days?.[0]?.day;
  // Before the listing lands there is no latest day to move, thus
  // no control is offered (the earlier page kept them hidden too).
  const movable =
    days !== null && (selected === null || selected.day === latestDay);
  const status = selected?.status ?? "none";

  const loadPreview = async () => {
    if (selected === null) {
      return;
    }
    setRankNote("scoring…");
    try {
      setRankings(await api.getRankings(selected.day));
      setRankNote("");
    } catch (error) {
      setRankNote(messageOf(error));
    }
  };

  return (
    <div
      style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}
    >
      <div
        style={{
          border: "1px dashed #bf616a",
          borderRadius: 8,
          padding: "8px 12px",
          fontSize: 13,
        }}
      >
        DEV CONSOLE — development only. Players use{" "}
        <a href="/">the player app</a>; nothing here is the production
        interface, and there is no sketch input on this page.
      </div>

      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        {days !== null && days.length > 0 ? (
          <select
            className="input"
            aria-label="stored day"
            style={{ width: "auto" }}
            value={selected?.day ?? ""}
            onChange={(event) => {
              const row = days.find((r) => r.day === event.target.value);
              if (row !== undefined) {
                void showDay(row);
              }
            }}
          >
            {days.map((row) => (
              <option key={row.day} value={row.day}>
                {row.day} · {row.trial_code} · {row.status}
                {row.submitted ? " · sent" : ""}
              </option>
            ))}
          </select>
        ) : null}
        <span style={{ fontSize: 13, color: "var(--color-neutral-500)" }}>
          {note === "" ? `status ${status}` : note}
        </span>
        <span style={{ flex: 1 }} />
        <a href="/history">history and skill number</a>
      </div>

      <div className="card" style={{ gap: 8 }}>
        <div
          style={{
            fontSize: 40,
            fontWeight: 700,
            letterSpacing: 6,
            fontFamily: "ui-monospace, Menlo, monospace",
          }}
        >
          {selected?.trial_code ?? "······"}
        </div>
        <div style={{ fontSize: 13 }}>{selected?.day ?? ""}</div>
        <div
          style={{
            fontSize: 12,
            color: "var(--color-neutral-500)",
            wordBreak: "break-all",
          }}
        >
          {selected?.commitment ?? ""}
        </div>
        <div
          id="day-controls"
          style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
        >
          {movable && status !== "open" ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => act(() => api.postOpen())}
            >
              Open the next day
            </button>
          ) : null}
          {movable && status === "open" ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() =>
                act(
                  () => api.postClose(),
                  "Close the day? Scoring runs and the window locks.",
                )
              }
            >
              Close the day (scores now)
            </button>
          ) : null}
          {movable && status === "closed" ? (
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => act(() => api.postReveal())}
            >
              Reveal
            </button>
          ) : null}
          <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            {controlNote === ""
              ? "each stored day is readable - the control row moves the latest one"
              : controlNote}
          </span>
        </div>
      </div>

      {selected === null ? null : (
        <div className="card" style={{ gap: 8 }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setTargetShown((shown) => !shown)}
            >
              {targetShown ? "Hide the target" : "Show the target"}
            </button>
            <span style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              hidden by default, so a blind run stays possible
            </span>
          </div>
          {targetShown ? (
            <img
              src={api.imageUrl(selected.target_id)}
              width={192}
              alt={`target for ${selected.day}`}
              style={{ borderRadius: 8 }}
            />
          ) : null}
        </div>
      )}

      {stored === null ? (
        <p className="text-muted" style={{ fontSize: 13 }} role="status">
          {dayNote === "" ? "loading…" : dayNote}
        </p>
      ) : (
        <>
          <SubmissionView stored={stored} />
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {rankings === null && status === "open" ? (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void loadPreview()}
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

      <details>
        <summary>How a day runs</summary>
        <ol style={{ fontSize: 13 }}>
          <li>Open the next day — the code appears.</li>
          <li>The player sends from the player app.</li>
          <li>Close the day — the one live step; scoring runs.</li>
          <li>Reveal — the target and the report go public.</li>
        </ol>
      </details>
    </div>
  );
}
