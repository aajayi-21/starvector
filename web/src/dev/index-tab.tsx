/**
 * The Results database tab (spec BR1 §7.3): the SQLite index made from
 * the store — its build time, whether it still agrees with the store,
 * each table's row count — and a read-only SQL box over it.
 *
 * The index is a cache: "Build again" rewrites the cache file from the
 * store and touches no play record. The server refuses every write in
 * the query box (three layers, see service/index.py), so the examples
 * here are all SELECTs and the box cannot change anything.
 */

import { useCallback, useEffect, useState } from "react";

import type { DevApi } from "./api";
import { DevApiError } from "./api";
import { refusedRead } from "./days-tab";
import { utcStamp } from "./format";
import type {
  DevCell,
  DevIndexCheck,
  DevIndexStatus,
  DevQueryResult,
} from "./types";

function messageOf(error: unknown): string {
  return error instanceof DevApiError ? error.message : "refused";
}

/** Starting points for the query box — each is a plain SELECT. */
export const EXAMPLES: ReadonlyArray<{ label: string; sql: string }> = [
  {
    label: "Revealed results",
    sql: `SELECT day, player, ROUND(p, 3) AS share_beaten,
       target_rank, decoy_count + 1 AS photos
FROM revealed_trials
ORDER BY day DESC, p DESC`,
  },
  {
    label: "Each player's results",
    sql: `SELECT player, COUNT(*) AS days,
       ROUND(AVG(p), 3) AS mean_share_beaten,
       ROUND(MIN(p), 3) AS lowest, ROUND(MAX(p), 3) AS highest
FROM revealed_trials
GROUP BY player
ORDER BY days DESC`,
  },
  {
    label: "Sends by day",
    sql: `SELECT d.day, d.status, d.trial_code, COUNT(s.player) AS sends,
       SUM(s.stroke_count > 0) AS with_sketch,
       SUM(s.impression_count > 0) AS with_words
FROM days AS d
LEFT JOIN submissions AS s ON s.day = d.day
GROUP BY d.day
ORDER BY d.day DESC`,
  },
  {
    label: "Words that connected",
    sql: `SELECT atom_text AS word, COUNT(*) AS uses,
       ROUND(AVG(similarity), 3) AS mean_similarity
FROM trial_atoms
WHERE atom_text IS NOT NULL
GROUP BY atom_text
ORDER BY uses DESC
LIMIT 50`,
  },
  {
    label: "Players and accounts",
    sql: `SELECT p.player, p.display_name, p.status, p.created_at,
       a.description, a.avatar_hash IS NOT NULL AS has_picture
FROM players AS p
LEFT JOIN accounts AS a ON a.player = p.player
ORDER BY p.created_at`,
  },
];

/** One cell for the table: NULL reads as NULL, not as an empty cell. */
function cellText(value: DevCell): string {
  return value === null ? "NULL" : String(value);
}

/** RFC 4180 CSV of the answer, for the download. */
export function toCsv(result: DevQueryResult): string {
  const quote = (value: DevCell): string => {
    const text = value === null ? "" : String(value);
    return /[",\n\r]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const lines = [result.columns.map(quote).join(",")];
  for (const row of result.rows) {
    lines.push(row.map(quote).join(","));
  }
  return `${lines.join("\r\n")}\r\n`;
}

function download(result: DevQueryResult): void {
  const blob = new Blob([toCsv(result)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "starvector-query.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export function IndexTab(props: {
  api: DevApi;
  reload: number;
}): React.JSX.Element {
  const { api, reload } = props;
  const [status, setStatus] = useState<DevIndexStatus | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [check, setCheck] = useState<DevIndexCheck | null>(null);
  const [actionNote, setActionNote] = useState("");
  const [sql, setSql] = useState(EXAMPLES[0]?.sql ?? "");
  const [result, setResult] = useState<DevQueryResult | null>(null);
  const [queryNote, setQueryNote] = useState("");
  const [querying, setQuerying] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.getIndex());
      setNote("");
    } catch (error) {
      setNote(refusedRead(error));
    }
  }, [api]);

  useEffect(() => {
    void reload;
    void load();
  }, [load, reload]);

  const build = async () => {
    setBusy(true);
    setActionNote("building…");
    setCheck(null);
    try {
      setStatus(await api.buildIndex());
      setActionNote("Built from the store.");
    } catch (error) {
      setActionNote(messageOf(error));
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true);
    setActionNote("checking…");
    setCheck(null);
    try {
      setCheck(await api.verifyIndex());
      setActionNote("");
    } catch (error) {
      setActionNote(messageOf(error));
    } finally {
      setBusy(false);
    }
  };

  const runQuery = async () => {
    if (sql.trim() === "" || querying) {
      return;
    }
    setQuerying(true);
    setQueryNote("");
    try {
      setResult(await api.queryIndex(sql));
      // The query builds a stale index first; read the status again.
      void load();
    } catch (error) {
      setResult(null);
      setQueryNote(messageOf(error));
    } finally {
      setQuerying(false);
    }
  };

  return (
    <div className="dev-stack">
      <section className="card dev-card" aria-label="Index file">
        {status === null ? (
          <p className="dev-muted" role="status">
            {note === "" ? "loading…" : note}
          </p>
        ) : (
          <>
            <div className="dev-row dev-wrap">
              <span
                className={`dev-dot ${
                  !status.exists || status.problem !== null
                    ? "dev-dot-off"
                    : status.current
                      ? "dev-dot-on"
                      : "dev-dot-warn"
                }`}
                aria-hidden="true"
              />
              <h2 className="dev-h2">
                {!status.exists
                  ? "Not built yet"
                  : status.problem !== null
                    ? "The index file does not read"
                    : status.current
                      ? "Up to date with the store"
                      : "Behind the store"}
              </h2>
            </div>
            <p className="dev-muted">
              {!status.exists
                ? "The first query builds it, or build it now."
                : status.problem !== null
                  ? status.problem
                  : status.current
                    ? `Built ${utcStamp(status.built_at)}.`
                    : `Built ${utcStamp(status.built_at)}; the store changed since. The next query builds it again.`}
            </p>
            <code className="dev-mono dev-break dev-muted">{status.path}</code>
            <div className="dev-row dev-wrap">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy}
                onClick={() => void build()}
              >
                Build again from the store
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={busy || !status.exists}
                onClick={() => void verify()}
              >
                Check against the store
              </button>
              <span className="dev-hint" role="status">
                {actionNote}
              </span>
            </div>
            {check === null ? null : check.agrees ? (
              <p className="dev-good" role="status">
                The index agrees with the store, table by table.
              </p>
            ) : (
              <ul className="dev-alert" role="alert">
                {check.problems.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
            {status.tables.length === 0 ? null : (
              <ul className="dev-chips" aria-label="Row counts">
                {status.tables.map((table) => (
                  <li key={table.name} className="dev-chip">
                    <span className="dev-mono">{table.name}</span>{" "}
                    <strong>{table.rows}</strong>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      <section className="card dev-card" aria-label="Query">
        <div className="dev-row dev-wrap">
          <span className="card-kicker">Query · read-only</span>
          <span style={{ flex: 1 }} />
          {EXAMPLES.map((example) => (
            <button
              key={example.label}
              type="button"
              className="btn btn-ghost dev-small"
              onClick={() => setSql(example.sql)}
            >
              {example.label}
            </button>
          ))}
        </div>
        <textarea
          className="input dev-sql"
          aria-label="SQL query"
          spellCheck={false}
          rows={7}
          value={sql}
          onChange={(event) => setSql(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              void runQuery();
            }
          }}
        />
        <div className="dev-row dev-wrap">
          <button
            type="button"
            className="btn btn-primary"
            disabled={querying || sql.trim() === ""}
            onClick={() => void runQuery()}
          >
            {querying ? "Running…" : "Run query"}
          </button>
          <span className="dev-hint">
            Ctrl+Enter runs it. One SELECT; 1,000 rows and 5 seconds at most.
            Trial rows exist for revealed days only.
          </span>
          <span style={{ flex: 1 }} />
          {result === null ? null : (
            <>
              <span className="dev-muted" role="status">
                {result.rows.length} {result.rows.length === 1 ? "row" : "rows"}
                {result.truncated
                  ? " (more rows exist — add a LIMIT or a WHERE)"
                  : ""}{" "}
                · {result.elapsed_ms} ms
              </span>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={result.rows.length === 0}
                onClick={() => download(result)}
              >
                Download CSV
              </button>
            </>
          )}
        </div>
        {queryNote === "" ? null : (
          <p className="dev-alert" role="alert">
            {queryNote}
          </p>
        )}
        {result === null ? null : result.rows.length === 0 ? (
          <p className="dev-muted">No rows.</p>
        ) : (
          <div className="dev-scroll">
            <table className="table dev-table dev-results">
              <thead>
                <tr>
                  {result.columns.map((column, index) => (
                    // Two columns can share a name (SELECT a, a).
                    // biome-ignore lint/suspicious/noArrayIndexKey: columns have no other key
                    <th key={`${column}-${index}`}>{column}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, rowIndex) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: result rows have no key
                  <tr key={rowIndex}>
                    {row.map((value, index) => (
                      <td
                        // biome-ignore lint/suspicious/noArrayIndexKey: cells follow the columns
                        key={index}
                        className={
                          value === null
                            ? "dev-null"
                            : typeof value === "number"
                              ? "dev-num"
                              : undefined
                        }
                        title={cellText(value)}
                      >
                        {cellText(value)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {status === null || status.tables.length === 0 ? null : (
        <details className="card dev-card dev-help">
          <summary>Tables and columns</summary>
          <dl className="dev-schema">
            {status.tables.map((table) => (
              <div key={table.name}>
                <dt className="dev-mono">
                  {table.name}
                  {table.view ? " (view: revealed days, pinned rows)" : ""}
                </dt>
                <dd className="dev-mono dev-muted">
                  {table.columns.join(", ")}
                </dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}
