/**
 * The rankings view: the trial line with the target position and
 * the rank after the near-duplicate group exits, the atom report,
 * and the full-pool table with per-channel columns. The target row
 * is always present in the top-25 slice; show-all reveals the
 * whole ordering.
 */

import { useState } from "react";

import type { DevApi } from "./api";
import type { DevRankings } from "./types";

const LEADERBOARD_LIMIT = 25;

export function RankingsView(props: {
  rankings: DevRankings;
  api: DevApi;
}): React.JSX.Element {
  const { rankings, api } = props;
  const [showAll, setShowAll] = useState(false);
  const rows = showAll
    ? rankings.rankings
    : [
        ...rankings.rankings.slice(0, LEADERBOARD_LIMIT),
        ...rankings.rankings
          .slice(LEADERBOARD_LIMIT)
          .filter((row) => row.is_target),
      ];
  const trial = rankings.trial;
  return (
    <div className="card">
      <div className="eyebrow">Rankings</div>
      <div className="small">
        trial score {trial.p.toFixed(4)} — target at position{" "}
        {rankings.target_position} of {rankings.rankings.length} (rank{" "}
        {trial.target_rank} of {trial.decoy_count + 1} after the near-duplicate
        group exits)
      </div>
      {rankings.report.length === 0 ? null : (
        <div className="dev-scroll-x">
          <table className="table dev-table">
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
              {rankings.report.map((row) => (
                <tr key={row.atom_id}>
                  <td>{row.atom_text}</td>
                  <td>{row.element ?? "-"}</td>
                  <td>{row.weight.toFixed(3)}</td>
                  <td>{row.similarity.toFixed(3)}</td>
                  <td>{row.rarity.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="dev-scroll-x">
        <table className="table dev-table dev-rankings">
          <thead>
            <tr>
              <th>#</th>
              <th aria-label="thumbnail" />
              <th>image</th>
              {rankings.channel_names.map((name) => (
                <th key={name}>{name}</th>
              ))}
              <th>fused</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.image_id}
                className={row.is_target ? "dev-target-row" : undefined}
              >
                <td>{row.position}</td>
                <td>
                  <img
                    src={api.imageUrl(row.image_id)}
                    width={40}
                    loading="lazy"
                    alt=""
                  />
                </td>
                <td className="dev-mono">
                  {row.image_id.slice(0, 8)}
                  {row.is_target ? " ← target" : ""}
                </td>
                {rankings.channel_names.map((name) => (
                  <td key={name}>{row.channels[name]?.toFixed(4) ?? "-"}</td>
                ))}
                <td>{row.fused.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!showAll && rankings.rankings.length > LEADERBOARD_LIMIT ? (
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setShowAll(true)}
        >
          Show the full ranking
        </button>
      ) : null}
    </div>
  );
}
