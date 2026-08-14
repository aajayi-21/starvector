/**
 * The history screen (mock 1d, spec W1 B9): the skill hero, stat
 * cards, the last-14 bars, and the revealed-days table linking each
 * row to its reveal report. Served by the mock adapter until the
 * backend phase implements GET /api/history.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../api/client";
import type { HistoryView, MeView } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";

function Kicker(props: { children: React.ReactNode }): React.JSX.Element {
  return (
    <div
      style={{
        fontSize: 11,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--color-neutral-500)",
      }}
    >
      {props.children}
    </div>
  );
}

function StatCard(props: { label: string; value: string }): React.JSX.Element {
  return (
    <div className="card" style={{ gap: 2 }}>
      <Kicker>{props.label}</Kicker>
      <div style={{ fontSize: 28, fontWeight: 500 }}>{props.value}</div>
    </div>
  );
}

export function HistoryScreen(): React.JSX.Element {
  const api = useApi();
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api.getHistory(),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });

  if (history.isPending) {
    return (
      <div style={{ padding: 28 }}>
        <p className="text-muted">Loading…</p>
      </div>
    );
  }
  if (history.isError || history.data === undefined) {
    return (
      <div style={{ padding: 28, maxWidth: 520 }}>
        <div className="card">
          <span className="card-kicker">History</span>
          {isRefusal(history.error) ? (
            <p className="text-muted">
              No revealed trial yet. Play a day first.
            </p>
          ) : (
            <p className="text-muted" role="alert">
              {friendlyMessage(history.error)}
            </p>
          )}
        </div>
      </div>
    );
  }
  return <HistoryBody view={history.data} me={me.data ?? null} />;
}

function HistoryBody(props: {
  view: HistoryView;
  me: MeView | null;
}): React.JSX.Element {
  const { view } = props;
  const streak = props.me?.streak ?? 0;
  const ps = view.days.map((row) => row.p);
  const best = view.days.reduce(
    (low, row) => (row.target_rank < low ? row.target_rank : low),
    Number.POSITIVE_INFINITY,
  );
  const sorted = [...ps].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const lastFourteen = view.days.slice(0, 14).reverse();
  const decoys = view.days[0]?.decoy_count ?? 0;

  return (
    <div className="history-columns">
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="card elev-sm" style={{ gap: 8 }}>
          <Kicker>Skill number</Kicker>
          {view.skill === null ? (
            <p className="text-muted">No revealed trial yet.</p>
          ) : (
            <>
              <div
                style={{
                  fontSize: 64,
                  lineHeight: 1,
                  fontWeight: 500,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {view.skill.theta.toFixed(3)}
              </div>
              <div style={{ fontSize: 13, color: "var(--color-neutral-400)" }}>
                shrunk {view.skill.shrunk.toFixed(3)} · evidence{" "}
                {view.skill.evidence_p.toFixed(3)} · {view.skill.n} trials
              </div>
              <div
                style={{
                  width: 48,
                  height: 2,
                  background: "var(--color-accent)",
                  marginTop: 4,
                }}
              />
              <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
                Above 1.0 means you beat chance more often than not. Keep
                sending.
              </div>
            </>
          )}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 14,
          }}
        >
          <StatCard label="Streak" value={`${streak} days`} />
          <StatCard
            label="Best rank"
            value={Number.isFinite(best) ? `${best} of ${decoys + 1}` : "—"}
          />
          <StatCard
            label="Median score"
            value={median === undefined ? "—" : median.toFixed(3)}
          />
          <StatCard label="Trials sent" value={`${view.days.length}`} />
        </div>
        {props.me === null ? null : (
          <div className="card" style={{ gap: 10 }}>
            <Kicker>Account</Kicker>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span
                aria-hidden="true"
                style={{
                  width: 36,
                  height: 36,
                  borderRadius: "50%",
                  background: "var(--color-neutral-800)",
                  color: "var(--color-neutral-200)",
                  display: "grid",
                  placeItems: "center",
                  fontSize: 13,
                  fontWeight: 500,
                }}
              >
                {props.me.player.slice(0, 2).toUpperCase()}
              </span>
              <div>
                <div style={{ fontSize: 14 }}>{props.me.player}</div>
                <div
                  style={{ fontSize: 12, color: "var(--color-neutral-500)" }}
                >
                  {props.me.public ? "public on leaderboard" : "not public yet"}
                </div>
              </div>
            </div>
            <label
              className="radio"
              style={{ opacity: 0.6 }}
              title="Daily reminders arrive with the backend phase."
            >
              <input
                type="checkbox"
                checked={props.me.reminder}
                disabled
                readOnly
              />
              <span style={{ fontSize: 13 }}>
                Daily reminder — not wired yet
              </span>
            </label>
          </div>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div className="card" style={{ gap: 10 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
            }}
          >
            <Kicker>Last {lastFourteen.length} trials</Kicker>
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              trial score, newest right
            </div>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "flex-end",
              gap: 8,
              height: 120,
            }}
            role="img"
            aria-label="trial scores, newest right"
          >
            {lastFourteen.map((row, index) => (
              <div
                key={row.day}
                title={`${row.day} · ${row.p.toFixed(4)}`}
                style={{
                  flex: 1,
                  height: `${Math.max(4, Math.round(row.p * 100))}%`,
                  background:
                    index >= lastFourteen.length - 2
                      ? "var(--color-accent-500)"
                      : index >= lastFourteen.length - 4
                        ? "var(--color-accent-700)"
                        : "var(--color-neutral-800)",
                  borderRadius: "3px 3px 0 0",
                }}
              />
            ))}
          </div>
        </div>
        <div className="card" style={{ gap: 10 }}>
          <Kicker>Revealed days</Kicker>
          <table className="table">
            <thead>
              <tr>
                <th>day</th>
                <th>code</th>
                <th>trial score</th>
                <th>rank</th>
                <th aria-label="report link" />
              </tr>
            </thead>
            <tbody>
              {view.days.map((row) => (
                <tr key={row.day}>
                  <td>{row.day}</td>
                  <td style={{ fontVariantNumeric: "tabular-nums" }}>
                    {row.trial_code}
                  </td>
                  <td>{row.p.toFixed(4)}</td>
                  <td>
                    {row.target_rank} of {row.decoy_count + 1}
                  </td>
                  <td>
                    <Link to="/reveal" search={{ day: row.day }}>
                      report
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
