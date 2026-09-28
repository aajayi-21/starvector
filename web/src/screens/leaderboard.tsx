/**
 * The leaderboard screen (spec M1 §9): the day's board and the
 * skill board, with the funnel chart as the skill board's primary
 * shape.
 *
 * Copy rules this screen is held to, each of them a decision and
 * none of them styling:
 *
 * - The rank, the rank interval and the trial count carry equal
 *   weight. No muted colour, no smaller size, no reduced opacity
 *   on any of the three, anywhere. §9 asks for equal weight and
 *   ARCHITECTURE §17 asks for the trial count prominently, and
 *   both are defeated by setting the uncertainty in small grey.
 * - The rank renders fractional. It is a posterior expectation,
 *   not a position in a sorted list.
 * - A fitted spread of zero reads "the players are not
 *   distinguishable at this time". That is a correct answer and it
 *   gets published as one.
 * - A variation statistic that misses its level is not evidence
 *   that the players are the same, and no sentence here says it
 *   is (spec M1 §6).
 * - No medals, no podium, no "good match" language.
 *
 * §6 asks for four numbers in its variation report. The fourth is
 * the population goodness-of-fit check, which ruling 5 of
 * 2026-08-15 holds for the operator, so this panel shows three and
 * the operator reads the fourth in the board artifact.
 */

import { useQuery } from "@tanstack/react-query";

import { useApi } from "../api/client";
import type {
  DiscoveryReport,
  LeaderboardView,
  PopulationFit,
  SkillBoardRow,
  SkillBoardView,
  VariationReport,
} from "../api/types";
import { friendlyMessage, isRefusal } from "../api/types";
import { boardSlice, funnelGeometry } from "../board/core";
import { AvatarCircle } from "../ui/avatar";
import { formatDay, ordinal, percentBeaten } from "../ui/format";
import { useNarrow } from "../ui/narrow";

/** How many ranked rows the table shows before the caller's own. */
const TABLE_LIMIT = 25;

/**
 * The plot box, in viewBox units. Not pixels: the SVG scales to
 * its column, and its type scales with it. The narrow box keeps
 * that scale factor near 1 on a phone, where the wide box would
 * render its 11-unit labels at about 6 px.
 */
const WIDE_PLOT = {
  width: 640,
  height: 340,
  left: 48,
  top: 16,
  right: 18,
  bottom: 46,
};
const NARROW_PLOT = {
  width: 360,
  height: 300,
  left: 40,
  top: 14,
  right: 14,
  bottom: 46,
};

const YOU = "var(--accent)";
const OTHERS = "var(--text-3)";

export function LeaderboardScreen(): React.JSX.Element {
  const api = useApi();
  const daily = useQuery({
    queryKey: ["leaderboard", "newest"],
    queryFn: () => api.getLeaderboard(),
  });
  const skill = useQuery({
    queryKey: ["skill-board"],
    queryFn: () => api.getSkillLeaderboard(),
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const self = me.data?.player ?? "";
  return (
    <div className="stack-lg">
      <div className="page-header" style={{ marginBottom: 0 }}>
        <h1>Leaderboard</h1>
        <p className="muted">
          The latest day's results, and the skill ranking across many days.
        </p>
      </div>
      <div className="two-columns">
        <div className="stack-lg">
          {skill.isPending ? (
            <p className="subtle">Loading…</p>
          ) : skill.isError || skill.data === undefined ? (
            <div className="notice notice-bad" role="alert">
              {friendlyMessage(skill.error)}
            </div>
          ) : (
            <SkillBoard view={skill.data} self={self} />
          )}
        </div>
        <div className="stack-lg">
          <DailyBoard
            view={daily.data}
            self={self}
            pending={daily.isPending}
            error={daily.isError ? daily.error : null}
          />
          {skill.data === undefined ? null : (
            <Population
              population={skill.data.population}
              variation={skill.data.variation}
              discovery={skill.data.discovery}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function DailyBoard(props: {
  view: LeaderboardView | undefined;
  self: string;
  pending: boolean;
  error: unknown;
}): React.JSX.Element {
  const { view, self, pending, error } = props;
  return (
    <section className="card" aria-labelledby="daily-heading">
      <div className="stack-sm">
        <h2 id="daily-heading">Latest day</h2>
        {view === undefined ? null : (
          <span className="subtle small">{formatDay(view.day)}</span>
        )}
      </div>
      {pending ? (
        <p className="subtle">Loading…</p>
      ) : view === undefined ? (
        isRefusal(error) ? (
          <p className="muted">
            No day has been revealed yet. This board fills in after the first
            one.
          </p>
        ) : (
          <div className="notice notice-bad" role="alert">
            {friendlyMessage(error)}
          </div>
        )
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>Player</th>
                <th className="num">Result</th>
                <th className="num">Photo's rank</th>
                <th className="num">Streak</th>
              </tr>
            </thead>
            <tbody>
              {view.rows.map((row) => (
                <tr
                  key={row.player}
                  className={row.player === self ? "is-you" : undefined}
                >
                  <td>
                    <PlayerCell
                      player={row.player}
                      displayName={row.display_name}
                      avatarHash={row.avatar_hash}
                      self={self}
                    />
                  </td>
                  <td className="num">{percentBeaten(row.p)}%</td>
                  <td className="num">
                    {ordinal(row.target_rank)} of {row.decoy_count + 1}
                  </td>
                  <td className="num">{row.streak}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * The board name cell (D5 as ruled 2026-08-21): the avatar beside
 * the label. The circle falls back to initials, so a board with no
 * pictures reads as it did before the ruling.
 */
function PlayerCell(props: {
  player: string;
  displayName: string;
  avatarHash: string | null;
  self: string;
}): React.JSX.Element {
  const { player, displayName, avatarHash, self } = props;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        fontWeight: player === self ? 650 : 400,
      }}
    >
      <AvatarCircle
        player={player}
        displayName={displayName}
        avatarHash={avatarHash}
        size={24}
      />
      <span>{player === self ? "You" : displayName}</span>
    </span>
  );
}

function SkillBoard(props: {
  view: SkillBoardView;
  self: string;
}): React.JSX.Element {
  const { view, self } = props;
  if (!view.active) {
    return <GatedBoard view={view} />;
  }
  const slice = boardSlice(view.rows, self, TABLE_LIMIT);
  const own = view.rows.find((row) => row.player === self) ?? null;
  return (
    <>
      <section className="card" aria-labelledby="skill-heading">
        <div className="stack-sm">
          <h2 id="skill-heading">Skill ranking</h2>
          <p className="hint">
            Each dot is a player: their skill number against how many results
            they've sent.
          </p>
        </div>
        {view.provisional ? <Provisional view={view} /> : null}
        <Funnel view={view} self={self} />
        <Legend />
      </section>
      {own !== null && !own.eligible ? (
        <NotYetRanked row={own} floor={view.eligibility_floor} />
      ) : null}
      {own?.eligible ? <OwnEvidence row={own} /> : null}
      <section className="card" aria-labelledby="ranked-heading">
        <h2 id="ranked-heading">Ranked players</h2>
        <RankedTable slice={slice} self={self} />
      </section>
    </>
  );
}

function GatedBoard(props: { view: SkillBoardView }): React.JSX.Element {
  const { view } = props;
  return (
    <section className="card card-hero" aria-labelledby="skill-heading">
      <h2 id="skill-heading">Skill ranking</h2>
      <p>
        The skill ranking starts once a player has sent {view.eligibility_floor}{" "}
        results. Nobody has yet.
      </p>
      <p className="muted small">
        A ranking needs that many results behind each number to mean anything.
        Until then, each day's results are on the right. After {view.fit_floor}{" "}
        players reach {view.eligibility_floor} results, the ranking stops being
        provisional.
      </p>
    </section>
  );
}

function Provisional(props: { view: SkillBoardView }): React.JSX.Element {
  const { view } = props;
  return (
    <div className="notice" role="note">
      Provisional — fewer than {view.fit_floor} players have{" "}
      {view.eligibility_floor} results ({view.eligible_count} so far), so the
      ranking assumes a typical spread between players instead of measuring it.
    </div>
  );
}

function Funnel(props: {
  view: SkillBoardView;
  self: string;
}): React.JSX.Element {
  const { view, self } = props;
  const plot = useNarrow() ? NARROW_PLOT : WIDE_PLOT;
  const geometry = funnelGeometry(view.rows, view.baseline_band, self);
  if (geometry.empty) {
    return <p className="muted">No players to draw yet.</p>;
  }
  const width = plot.width - plot.left - plot.right;
  const height = plot.height - plot.top - plot.bottom;
  const px = (x: number): number => plot.left + x * width;
  const py = (y: number): number => plot.top + y * height;
  // The band as one closed shape: along the top edge, back along
  // the bottom. Solid edges — a dashed one reads as a threshold,
  // and there is no threshold anywhere on this chart.
  const outline = [
    ...geometry.band.map((edge) => `${px(edge.x)},${py(edge.top)}`),
    ...[...geometry.band]
      .reverse()
      .map((edge) => `${px(edge.x)},${py(edge.bottom)}`),
  ].join(" ");
  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${plot.width} ${plot.height}`}
        style={{ width: "100%", height: "auto" }}
        role="img"
        aria-label={
          `Skill number against results sent for ${geometry.points.length} ` +
          "players, with the range play with no skill produces at each count."
        }
      >
        <title>Skill number against results sent</title>
        {geometry.skillTicks.map((tick) => (
          <g key={`skill-${tick.value}`}>
            <line
              x1={plot.left}
              x2={plot.left + width}
              y1={py(tick.position)}
              y2={py(tick.position)}
              stroke={tick.value === 1 ? "var(--chance)" : "var(--border)"}
              strokeWidth={tick.value === 1 ? 2 : 1}
            />
            <text
              x={plot.left - 8}
              y={py(tick.position) + 4}
              textAnchor="end"
              fontSize={11}
              fill="var(--text-3)"
            >
              {tick.label}
            </text>
          </g>
        ))}
        {geometry.trialTicks.map((tick) => (
          <text
            key={`trials-${tick.value}`}
            x={px(tick.position)}
            y={plot.height - 26}
            textAnchor="middle"
            fontSize={11}
            fill="var(--text-3)"
          >
            {tick.label}
          </text>
        ))}
        {geometry.band.length > 1 ? (
          <polygon
            points={outline}
            fill="var(--surface-2)"
            fillOpacity={0.9}
            stroke="var(--border-strong)"
            strokeWidth={1}
          />
        ) : null}
        {geometry.points.map((point) => (
          <circle
            key={point.player}
            cx={px(point.x)}
            cy={py(point.y)}
            r={point.self ? 6 : 4}
            fill={point.self ? YOU : point.eligible ? OTHERS : "transparent"}
            stroke={point.self ? YOU : OTHERS}
            strokeWidth={point.eligible ? 0 : 1.5}
          >
            {/* An SVG title is an element. The HTML title attribute
                does not carry over. */}
            <title>
              {point.self ? "You" : point.display_name} — skill number{" "}
              {point.theta.toFixed(2)} after {point.n}{" "}
              {point.n === 1 ? "result" : "results"}
              {point.eligible ? "" : " (not ranked yet)"}
            </title>
          </circle>
        ))}
        <text
          x={plot.left + width / 2}
          y={plot.height - 6}
          textAnchor="middle"
          fontSize={11}
          fill="var(--text-3)"
        >
          results sent
        </text>
      </svg>
    </figure>
  );
}

function Legend(): React.JSX.Element {
  return (
    <div className="stack-sm">
      <div className="row" style={{ gap: 16 }}>
        <Swatch fill={YOU} stroke={YOU}>
          You
        </Swatch>
        <Swatch fill={OTHERS} stroke={OTHERS}>
          Ranked
        </Swatch>
        <Swatch fill="transparent" stroke={OTHERS}>
          Not ranked yet
        </Swatch>
      </div>
      <p className="hint">
        The line at 1.00 is chance. The shaded band is where players with no
        skill land. It narrows to the right because more results pin a number
        down — so a high dot on the left means less than a high dot on the
        right.
      </p>
    </div>
  );
}

function Swatch(props: {
  fill: string;
  stroke: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <span
      className="small"
      style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
    >
      <svg width={14} height={14} aria-hidden="true">
        <circle
          cx={7}
          cy={7}
          r={5}
          fill={props.fill}
          stroke={props.stroke}
          strokeWidth={1.5}
        />
      </svg>
      {props.children}
    </span>
  );
}

/**
 * The caller's own evidence, as a natural frequency (ruling 15).
 *
 * `anytime_significance` is 1/E, and Ville's inequality says that
 * with no skill the chance of ever getting to 1/α is at most α.
 * "Fewer than 1 player in 340 with no skill ever gets here" is
 * therefore literally what the number promises, and unlike a
 * fixed-count p-value it survives the player choosing when to
 * stop. The raw value sits beside it for anyone who wants it.
 */
function OwnEvidence(props: { row: SkillBoardRow }): React.JSX.Element {
  const { row } = props;
  return (
    <section className="card" aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">How unusual your results are</h2>
      <p>{evidenceSentence(row.anytime_significance)}</p>
      <p className="hint">
        This holds however often you check and whenever you stop. Evidence
        score: {evidenceE(row)} (1 means no evidence at all).
      </p>
    </section>
  );
}

export function evidenceSentence(significance: number): string {
  if (significance >= 1) {
    return "Your results so far are what no skill at all produces.";
  }
  const inN = Math.round(1 / significance);
  if (inN < 2) {
    return "Your results so far are close to what no skill at all produces.";
  }
  return `Fewer than 1 player in ${inN.toLocaleString()} with no skill ever gets to where you are.`;
}

function evidenceE(row: SkillBoardRow): string {
  return Math.exp(row.log_e_value).toLocaleString(undefined, {
    maximumFractionDigits: 1,
  });
}

function NotYetRanked(props: {
  row: SkillBoardRow;
  floor: number;
}): React.JSX.Element {
  const { row, floor } = props;
  return (
    <section className="card" aria-labelledby="standing-heading">
      <h2 id="standing-heading">Where you stand</h2>
      <p>
        You've sent {row.n} of the {floor} results a ranking needs.
      </p>
      <p className="hint">
        Your dot is on the chart already. Until {floor} results, the range
        around it is too wide for a rank to mean much.
      </p>
    </section>
  );
}

function RankedTable(props: {
  slice: ReturnType<typeof boardSlice>;
  self: string;
}): React.JSX.Element {
  const { slice, self } = props;
  return (
    <>
      <div className="table-scroll">
        <table className="table" data-testid="ranked-table">
          <thead>
            <tr>
              <th className="num">Rank</th>
              <th>Player</th>
              <th className="num">Skill</th>
              <th className="num">Likely rank</th>
              <th className="num">Results</th>
            </tr>
          </thead>
          <tbody>
            {slice.shown.map((row) => (
              <RankedRow key={row.player} row={row} self={self} />
            ))}
            {slice.pinned === null ? null : (
              <>
                <tr>
                  <td colSpan={5} style={{ padding: 0 }}>
                    <hr className="divider" />
                  </td>
                </tr>
                <RankedRow row={slice.pinned} self={self} />
              </>
            )}
          </tbody>
        </table>
      </div>
      {slice.total > slice.shown.length ? (
        <p className="hint">
          Showing {slice.shown.length} of {slice.total.toLocaleString()} ranked
          players.
        </p>
      ) : null}
    </>
  );
}

function RankedRow(props: {
  row: SkillBoardRow;
  self: string;
}): React.JSX.Element {
  const { row, self } = props;
  const mine = row.player === self;
  // The rank, the range, and the result count carry equal weight
  // (spec M1 §9): no muted colour and no smaller size on any of them.
  return (
    <tr className={mine ? "is-you" : undefined}>
      {/* Fractional: a posterior expectation, not a position. */}
      <td className="num">{row.expected_rank?.toFixed(1) ?? "—"}</td>
      <td>
        <PlayerCell
          player={row.player}
          displayName={row.display_name}
          avatarHash={row.avatar_hash}
          self={self}
        />
      </td>
      <td className="num">
        {row.shrunk === null ? "—" : Math.exp(row.shrunk).toFixed(2)}
      </td>
      <td className="num">
        {row.rank_low ?? "—"} to {row.rank_high ?? "—"}
      </td>
      <td className="num">{row.n}</td>
    </tr>
  );
}

function Population(props: {
  population: PopulationFit | null;
  variation: VariationReport | null;
  discovery: DiscoveryReport | null;
}): React.JSX.Element | null {
  const { population, variation, discovery } = props;
  if (population === null) {
    return null;
  }
  return (
    <section className="card" aria-labelledby="population-heading">
      <h2 id="population-heading">All players</h2>
      {population.tau === 0 ? (
        <p>
          Players can't be told apart yet. The spread between them is estimated
          at zero — a real answer, not a missing one: so far the results look
          like chance alone.
        </p>
      ) : (
        <p>
          From player to player, skill numbers differ by about{" "}
          {variation === null
            ? "—"
            : `${variation.tau_multiplicative.toFixed(2)}×`}
          .
        </p>
      )}
      {discovery === null ? null : (
        <p>
          {discovery.flagged} of {discovery.tested} players stand out above
          chance. About {discovery.expected_by_luck.toFixed(1)} of those would
          stand out by luck alone.
        </p>
      )}
      {variation === null ? null : (
        <details className="disclosure">
          <summary>The numbers</summary>
          <div className="disclosure-body">
            <table className="table">
              <tbody>
                <tr>
                  <td>Spread between players</td>
                  <td className="num">
                    {population.tau.toFixed(3)} ({variation.tau_low.toFixed(3)}{" "}
                    to{" "}
                    {variation.tau_high === null
                      ? "no upper limit"
                      : variation.tau_high.toFixed(3)}
                    )
                  </td>
                </tr>
                <tr>
                  <td>Variation test</td>
                  <td className="num">
                    {variation.q_statistic.toFixed(1)} on {variation.dof}{" "}
                    degrees of freedom, p ={" "}
                    {variation.q_significance.toFixed(4)}
                  </td>
                </tr>
                <tr>
                  <td>Where a new player is likely to land</td>
                  <td className="num">
                    {Math.exp(variation.prediction_low).toFixed(2)} to{" "}
                    {Math.exp(variation.prediction_high).toFixed(2)}
                  </td>
                </tr>
              </tbody>
            </table>
            {variation.q_significance > 0.05 ? (
              <p className="hint">
                The variation test doesn't clear its level. That isn't evidence
                that players are the same — the results so far don't settle it
                either way.
              </p>
            ) : null}
          </div>
        </details>
      )}
    </section>
  );
}
