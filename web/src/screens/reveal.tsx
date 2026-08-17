/**
 * The reveal screen (mock 1c, spec W1 B8): the score hero derives
 * from the trial row fields alone, the commitment check line ships
 * verbatim, the sketch replays from the stored record (locally kept
 * sent copy as fallback), and the leaderboard card runs on the mock
 * adapter until the backend phase.
 */

import { useQuery } from "@tanstack/react-query";
import { useSearch } from "@tanstack/react-router";

import { useApi } from "../api/client";
import type { RevealView, TrialValue, WireRecord } from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { ReplayCanvas } from "../sketch/canvas";
import { Kicker } from "../ui/kicker";

function readSentCopy(day: string): WireRecord | null {
  try {
    const raw = window.localStorage.getItem(`sv:sent:${day}`);
    return raw === null ? null : (JSON.parse(raw) as WireRecord);
  } catch {
    return null;
  }
}

/**
 * Today's p minus the median of the prior revealed p values —
 * hidden when there are fewer than two priors (spec W1 §3).
 */
export function medianDelta(
  p: number,
  day: string,
  history: ReadonlyArray<{ day: string; p: number }>,
): number | null {
  const priors = history
    .filter((row) => row.day < day)
    .map((row) => row.p)
    .sort((a, b) => a - b);
  if (priors.length < 2) {
    return null;
  }
  const half = Math.floor(priors.length / 2);
  const median =
    priors.length % 2 === 1
      ? (priors[half] ?? 0)
      : ((priors[half - 1] ?? 0) + (priors[half] ?? 0)) / 2;
  return p - median;
}

export function RevealScreen(): React.JSX.Element {
  const api = useApi();
  const search = useSearch({ from: "/reveal" });
  const reveal = useQuery({
    queryKey: ["reveal", search.day ?? "latest"],
    queryFn: () => api.getReveal(search.day),
  });

  if (reveal.isPending) {
    return (
      <div style={{ padding: 28 }}>
        <p className="text-muted">Loading…</p>
      </div>
    );
  }
  if (reveal.isError || reveal.data === undefined) {
    return (
      <div style={{ padding: 28, maxWidth: 520 }}>
        <div className="card">
          <span className="card-kicker">Reveal</span>
          {isRefusal(reveal.error) ? (
            <p className="text-muted">
              Not revealed yet. The reveal opens after the day closes and the
              operator scores it.
            </p>
          ) : (
            <p className="text-muted" role="alert">
              {friendlyMessage(reveal.error)}
            </p>
          )}
        </div>
      </div>
    );
  }
  return <RevealBody view={reveal.data} />;
}

function RevealBody(props: { view: RevealView }): React.JSX.Element {
  const api = useApi();
  const { view } = props;
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api.getHistory(),
  });
  const leaderboard = useQuery({
    queryKey: ["leaderboard", view.day],
    queryFn: () => api.getLeaderboard(view.day),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const submission = useQuery({
    queryKey: ["submission", view.day],
    queryFn: () => api.getSubmission(view.day),
    retry: false,
  });

  const sentCopy = readSentCopy(view.day);
  const replayRecord = submission.data?.record ?? sentCopy;
  const delta =
    view.trial === null || history.data === undefined
      ? null
      : medianDelta(view.trial.p, view.day, history.data.days);

  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "24px 28px 8px" }}>
        <div
          style={{
            fontSize: 11,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--color-accent)",
          }}
        >
          Reveal · {view.day}
        </div>
      </div>
      <div className="reveal-columns">
        <div className="card elev-sm" style={{ gap: 10 }}>
          <Kicker>Trial score</Kicker>
          {view.trial === null ? (
            <p className="text-muted">No submission this day.</p>
          ) : (
            <ScoreHero trial={view.trial} delta={delta} />
          )}
          <div className="hr" style={{ margin: "6px 0" }} />
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            commitment{" "}
            <span style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>
              {view.commitment}
            </span>
          </div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
            secret{" "}
            <span style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>
              {view.secret}
            </span>
          </div>
          <div
            style={{
              fontSize: 12,
              color: "var(--color-neutral-500)",
              fontFamily: "ui-monospace, Menlo, monospace",
            }}
          >
            {view.check}
          </div>
        </div>
        <div className="card" style={{ gap: 8 }}>
          <Kicker>The target was</Kicker>
          <img
            className="lighten"
            src={api.imageUrl(view.target_id)}
            alt={`revealed target for ${view.day}`}
            style={{ width: "100%", aspectRatio: "1 / 1", borderRadius: 8 }}
          />
        </div>
        <div className="card" style={{ gap: 8 }}>
          <Kicker>Your sketch</Kicker>
          {replayRecord === null || replayRecord === undefined ? (
            <p className="text-muted" style={{ fontSize: 13 }}>
              No stored sketch to replay on this device.
            </p>
          ) : (
            <ReplayCanvas strokes={replayRecord.canvas_strokes} />
          )}
        </div>
      </div>
      <div className="reveal-tables">
        {view.report.length === 0 ? null : (
          <div className="card" style={{ gap: 10 }}>
            <Kicker>What matched</Kicker>
            <table className="table">
              <thead>
                <tr>
                  <th>atom</th>
                  <th>matched element</th>
                  <th>weight</th>
                  <th>similarity</th>
                  <th>rarity</th>
                </tr>
              </thead>
              <tbody>
                {view.report.map((row) => (
                  <tr key={row.atom_id}>
                    <td>{row.atom_text}</td>
                    <td>{row.element ?? "-"}</td>
                    <td>{row.weight.toFixed(3)}</td>
                    <td>{row.similarity.toFixed(3)}</td>
                    <td>
                      <span
                        className={
                          row.rarity >= 1.5
                            ? "tag tag-accent"
                            : "tag tag-neutral"
                        }
                      >
                        {row.rarity.toFixed(2)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {leaderboard.data === undefined ? null : (
          <div className="card" style={{ gap: 10 }}>
            <Kicker>Today's leaderboard</Kicker>
            <table className="table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>player</th>
                  <th>score</th>
                  <th>rank</th>
                  <th>streak</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.data.rows.map((row, index) => (
                  <tr
                    key={row.player}
                    style={
                      row.player === me.data?.player
                        ? { color: "var(--color-accent-300)" }
                        : undefined
                    }
                  >
                    <td>{index + 1}</td>
                    {/* Key and compare on the store key, which is
                        unique; render the label, which is not. */}
                    <td>
                      {row.player === me.data?.player
                        ? "you"
                        : row.display_name}
                    </td>
                    <td>{row.p.toFixed(4)}</td>
                    <td>
                      {row.target_rank} of {row.decoy_count + 1}
                    </td>
                    <td>{row.streak}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function ScoreHero(props: {
  trial: TrialValue;
  delta: number | null;
}): React.JSX.Element {
  const { trial, delta } = props;
  return (
    <>
      <div
        style={{
          fontSize: 64,
          lineHeight: 1,
          fontWeight: 500,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {trial.p.toFixed(4)}
      </div>
      <div style={{ fontSize: 14, color: "var(--color-neutral-400)" }}>
        You beat{" "}
        <strong style={{ color: "var(--color-text)" }}>
          {trial.beaten} of {trial.decoy_count}
        </strong>{" "}
        decoys — rank {trial.target_rank} of {trial.decoy_count + 1}.
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <span className="tag tag-accent">rank {trial.target_rank}</span>
        {delta === null ? null : (
          <span className="tag tag-neutral" style={{ whiteSpace: "nowrap" }}>
            {delta >= 0 ? "+" : ""}
            {delta.toFixed(3)} vs median
          </span>
        )}
      </div>
    </>
  );
}
