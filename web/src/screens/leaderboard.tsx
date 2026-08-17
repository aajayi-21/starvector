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
import { Kicker } from "../ui/kicker";
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

const YOU = "var(--color-accent-400)";
const OTHERS = "var(--color-neutral-600)";

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
    <div className="leaderboard-columns">
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        {skill.isPending ? (
          <p className="text-muted">Loading…</p>
        ) : skill.isError || skill.data === undefined ? (
          <div className="card">
            <span className="card-kicker">Skill board</span>
            <p className="text-muted" role="alert">
              {friendlyMessage(skill.error)}
            </p>
          </div>
        ) : (
          <SkillBoard view={skill.data} self={self} />
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
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
    <div className="card" style={{ gap: 10 }}>
      <Kicker>The day's board</Kicker>
      {pending ? (
        <p className="text-muted">Loading…</p>
      ) : view === undefined ? (
        isRefusal(error) ? (
          <p className="text-muted">
            No day has been revealed yet. The board opens after the first
            reveal.
          </p>
        ) : (
          <p className="text-muted" role="alert">
            {friendlyMessage(error)}
          </p>
        )
      ) : (
        <>
          <div style={{ fontSize: 13 }}>{view.day}</div>
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
              {view.rows.map((row, index) => (
                <tr
                  key={row.player}
                  style={
                    row.player === self
                      ? { color: "var(--color-accent-300)" }
                      : undefined
                  }
                >
                  <td>{index + 1}</td>
                  <td>{row.player === self ? "you" : row.display_name}</td>
                  <td>{row.p.toFixed(4)}</td>
                  <td>
                    {row.target_rank} of {row.decoy_count + 1}
                  </td>
                  <td>{row.streak}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
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
      <div className="card" style={{ gap: 12 }}>
        <Kicker>The skill board</Kicker>
        {view.provisional ? <Provisional view={view} /> : null}
        <Funnel view={view} self={self} />
        <Legend />
      </div>
      {own !== null && !own.eligible ? (
        <NotYetRanked row={own} floor={view.eligibility_floor} />
      ) : null}
      {own !== null && own.eligible ? <OwnEvidence row={own} /> : null}
      <div className="card" style={{ gap: 10 }}>
        <Kicker>Ranked</Kicker>
        <RankedTable slice={slice} self={self} />
      </div>
    </>
  );
}

function GatedBoard(props: { view: SkillBoardView }): React.JSX.Element {
  const { view } = props;
  return (
    <div className="card" style={{ gap: 10 }}>
      <Kicker>The skill board</Kicker>
      <p style={{ margin: 0 }}>
        The skill board opens when a player has {view.eligibility_floor} trials.
      </p>
      <p className="text-muted" style={{ margin: 0 }}>
        {view.eligible_count} of {view.fit_floor} eligible players so far. A
        ranking wants enough trials behind each number to mean anything, and
        nobody has that yet.
      </p>
    </div>
  );
}

function Provisional(props: { view: SkillBoardView }): React.JSX.Element {
  const { view } = props;
  return (
    <p className="tag tag-outline" style={{ alignSelf: "flex-start" }}>
      Provisional — {view.eligible_count} of {view.fit_floor} eligible players,
      so the population is assumed rather than fitted
    </p>
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
    return <p className="text-muted">No players to draw yet.</p>;
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
          `Skill number against trial count for ${geometry.points.length} ` +
          "players, with the range no-skill play produces at each trial count."
        }
      >
        <title>Skill number against trial count</title>
        {geometry.skillTicks.map((tick) => (
          <g key={`skill-${tick.value}`}>
            <line
              x1={plot.left}
              x2={plot.left + width}
              y1={py(tick.position)}
              y2={py(tick.position)}
              stroke={
                tick.value === 1
                  ? "var(--color-neutral-600)"
                  : "var(--color-divider)"
              }
              strokeWidth={1}
            />
            <text
              x={plot.left - 8}
              y={py(tick.position) + 4}
              textAnchor="end"
              fontSize={11}
              fill="var(--color-neutral-500)"
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
            fill="var(--color-neutral-500)"
          >
            {tick.label}
          </text>
        ))}
        {geometry.band.length > 1 ? (
          <polygon
            points={outline}
            fill="var(--color-neutral-800)"
            fillOpacity={0.55}
            stroke="var(--color-neutral-700)"
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
              {point.self ? "you" : point.display_name} — skill number{" "}
              {point.theta.toFixed(3)} over {point.n}{" "}
              {point.n === 1 ? "trial" : "trials"}
              {point.eligible ? "" : " (not ranked yet)"}
            </title>
          </circle>
        ))}
        <text
          x={plot.left + width / 2}
          y={plot.height - 6}
          textAnchor="middle"
          fontSize={11}
          fill="var(--color-neutral-400)"
        >
          trials
        </text>
      </svg>
    </figure>
  );
}

function Legend(): React.JSX.Element {
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 16,
        fontSize: 13,
        alignItems: "center",
      }}
    >
      <Swatch fill={YOU} stroke={YOU}>
        you
      </Swatch>
      <Swatch fill={OTHERS} stroke={OTHERS}>
        ranked
      </Swatch>
      <Swatch fill="transparent" stroke={OTHERS}>
        not ranked yet
      </Swatch>
      <span style={{ color: "var(--color-neutral-400)" }}>
        The brighter line at 1.00 is chance. The shaded range is what play with
        no skill produces at that trial count — it narrows to the right because
        more trials pin a number down, which is why a high dot on the left says
        much less than a high dot on the right.
      </span>
    </div>
  );
}

function Swatch(props: {
  fill: string;
  stroke: string;
  children: React.ReactNode;
}): React.JSX.Element {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
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
    <div className="card" style={{ gap: 8 }}>
      <Kicker>Your evidence</Kicker>
      <p style={{ margin: 0 }}>{evidenceSentence(row.anytime_significance)}</p>
      <p className="text-muted" style={{ margin: 0 }}>
        This holds however many times you look and whenever you stop, which a
        fixed-count significance value does not. E = {evidenceE(row)}, and 1 is
        no evidence at all.
      </p>
    </div>
  );
}

export function evidenceSentence(significance: number): string {
  if (significance >= 1) {
    return "Your play so far is what no skill at all produces.";
  }
  const inN = Math.round(1 / significance);
  if (inN < 2) {
    return "Your play so far is close to what no skill at all produces.";
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
    <div className="card" style={{ gap: 8 }}>
      <Kicker>Where you stand</Kicker>
      <p style={{ margin: 0 }}>
        {row.n} of {floor} trials. You join the ranking at {floor}.
      </p>
      <p className="text-muted" style={{ margin: 0 }}>
        Your dot is on the chart already. Until then the range around it is wide
        enough that a rank would say more than the trials support.
      </p>
    </div>
  );
}

function RankedTable(props: {
  slice: ReturnType<typeof boardSlice>;
  self: string;
}): React.JSX.Element {
  const { slice, self } = props;
  return (
    <>
      <table className="table" data-testid="ranked-table">
        <thead>
          <tr>
            <th>rank</th>
            <th>player</th>
            <th>skill</th>
            <th>range</th>
            <th>trials</th>
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
                  <div className="hr" />
                </td>
              </tr>
              <RankedRow row={slice.pinned} self={self} />
            </>
          )}
        </tbody>
      </table>
      {slice.total > slice.shown.length ? (
        <div style={{ fontSize: 13 }}>
          Showing {slice.shown.length} of {slice.total.toLocaleString()} ranked
          players.
        </div>
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
  return (
    <tr style={mine ? { color: "var(--color-accent-300)" } : undefined}>
      {/* Fractional: a posterior expectation, not a position. */}
      <td style={{ fontVariantNumeric: "tabular-nums" }}>
        {row.expected_rank?.toFixed(1) ?? "—"}
      </td>
      <td>{mine ? "you" : row.display_name}</td>
      <td style={{ fontVariantNumeric: "tabular-nums" }}>
        {row.shrunk === null ? "—" : Math.exp(row.shrunk).toFixed(3)}
      </td>
      {/* No muted colour and no smaller size on these two. */}
      <td style={{ fontVariantNumeric: "tabular-nums" }}>
        {row.rank_low ?? "—"} to {row.rank_high ?? "—"}
      </td>
      <td style={{ fontVariantNumeric: "tabular-nums" }}>{row.n}</td>
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
    <div className="card" style={{ gap: 10 }}>
      <Kicker>The population</Kicker>
      {population.tau === 0 ? (
        <p style={{ margin: 0 }}>
          The players are not distinguishable at this time. The spread between
          them is estimated at zero, which is a real answer and not a missing
          one: what the scores show so far is what chance alone produces.
        </p>
      ) : (
        <p style={{ margin: 0 }}>
          Player to player, skill numbers span about{" "}
          {variation === null
            ? "—"
            : `${variation.tau_multiplicative.toFixed(2)}×`}
          .
        </p>
      )}
      {variation === null ? null : (
        <table className="table">
          <tbody>
            <tr>
              <td>spread between players</td>
              <td style={{ fontVariantNumeric: "tabular-nums" }}>
                {population.tau.toFixed(3)} ({variation.tau_low.toFixed(3)} to{" "}
                {variation.tau_high === null
                  ? "unbounded"
                  : variation.tau_high.toFixed(3)}
                )
              </td>
            </tr>
            <tr>
              <td>variation statistic</td>
              <td style={{ fontVariantNumeric: "tabular-nums" }}>
                {variation.q_statistic.toFixed(1)} on {variation.dof} degrees of
                freedom, significance {variation.q_significance.toFixed(4)}
              </td>
            </tr>
            <tr>
              <td>where a new player is likely to land</td>
              <td style={{ fontVariantNumeric: "tabular-nums" }}>
                {Math.exp(variation.prediction_low).toFixed(3)} to{" "}
                {Math.exp(variation.prediction_high).toFixed(3)}
              </td>
            </tr>
          </tbody>
        </table>
      )}
      {variation !== null && variation.q_significance > 0.05 ? (
        <p className="text-muted" style={{ margin: 0 }}>
          The variation statistic does not clear its level. That is not evidence
          that the players are the same — it means the scores so far do not
          settle the question either way.
        </p>
      ) : null}
      {discovery === null ? null : (
        <p style={{ margin: 0 }}>
          {discovery.flagged} of {discovery.tested} players are flagged above
          the baseline. About {discovery.expected_by_luck.toFixed(1)} of those
          are flagged by luck alone.
        </p>
      )}
    </div>
  );
}
