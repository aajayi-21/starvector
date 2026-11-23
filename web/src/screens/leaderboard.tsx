/**
 * The leaderboard screen (spec M1 §9), in two parts behind two tabs.
 *
 * - **The day** (the owner's design of 2026-11-22): the photo of a
 *   revealed day beside the podium of its first three, the river of
 *   the day's sketches, and the rest of that day's board as a plain
 *   table (screens/leaderboard-day.tsx). A row of days steps through
 *   each revealed day.
 * - **Skill ranking**: the funnel chart as the primary shape, with the
 *   caller's own evidence and the facts of all players, then the
 *   ranked table at the full width. The chart is a star chart: each
 *   player is a star, on the band where players with no skill land.
 *
 * The tab and the day live in the path (`?board=skill`, `?day=…`), so
 * a reload and the back button keep them. A quiet sky of stars stands
 * behind the head of the page. Nothing here has a box.
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
 * - No medals and no "good match" language. The podium of the day
 *   sets the first three apart by the order the board gives them,
 *   with no medal and no color for a place (ui/podium.tsx).
 *
 * §6 asks for four numbers in its variation report. The fourth is
 * the population goodness-of-fit check, which ruling 5 of
 * 2026-08-15 holds for the operator, so this panel shows three and
 * the operator reads the fourth in the board artifact.
 */

import { CalendarBlank, CaretLeft, CaretRight } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useId, useRef, useState } from "react";

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
import { type AxisTick, boardSlice, funnelGeometry } from "../board/core";
import { seedOf } from "../sky/core";
import { createQuietSky } from "../sky/quiet";
import { AvatarCircle } from "../ui/avatar";
import { useDayNames } from "../ui/day-names";
import {
  Calendar,
  type CalendarDay,
  useCalendarClose,
} from "../ui/day-stepper";
import { dateKey, monthOf } from "../ui/month-grid";
import { useNarrow } from "../ui/narrow";
import { StreakName } from "../ui/streak-name";
import { DayBoard } from "./leaderboard-day";

/**
 * How many ranked rows the table shows before the caller's own, and
 * how many more each press of the button adds. Layout limits only.
 */
const TABLE_LIMIT = 12;
const TABLE_STEP = 25;

/**
 * The plot box, in viewBox units. Not pixels: the SVG scales to
 * its column, and its type scales with it. The narrow box keeps
 * that scale factor near 1 on a phone, where the wide box would
 * render its labels at about 6 px.
 */
const WIDE_PLOT = {
  width: 800,
  height: 394,
  left: 60,
  top: 20,
  right: 30,
  bottom: 54,
};
const NARROW_PLOT = {
  width: 358,
  height: 262,
  left: 40,
  top: 16,
  right: 10,
  bottom: 46,
};

/** The two parts of the screen. */
type Board = "day" | "skill";

const TABS: ReadonlyArray<readonly [Board, string]> = [
  ["day", "The day"],
  ["skill", "Skill ranking"],
];

/** The id of the tab of a part, for the panel to name. */
function tabId(board: Board): string {
  return `board-tab-${board}`;
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function LeaderboardScreen(): React.JSX.Element {
  const api = useApi();
  const navigate = useNavigate();
  const names = useDayNames();
  const search = useSearch({ from: "/leaderboard" });
  const board: Board = search.board === "skill" ? "skill" : "day";
  // No day names the newest revealed one, as the server reads it.
  const daily = useQuery({
    queryKey: ["leaderboard", search.day ?? "newest"],
    queryFn: () => api.getLeaderboard(search.day),
  });
  const skill = useQuery({
    queryKey: ["skill-board"],
    queryFn: () => api.getSkillLeaderboard(),
  });
  // The list of revealed days, the newest first, with the code of each.
  // The key and the request of the practice screen: one read serves both.
  const days = useQuery({
    queryKey: ["practice-days"],
    queryFn: () => api.getPracticeDays(),
    retry: false,
  });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const self = me.data?.player ?? "";
  const panel = useRef<HTMLDivElement | null>(null);

  const day = daily.data?.day ?? search.day;
  const revealed = (days.data?.days ?? []).map((row) => row.day);
  const code = days.data?.days.find((row) => row.day === day)?.trial_code;
  const count = daily.data?.rows.length;
  const findable =
    board === "day"
      ? (daily.data?.rows.some((row) => row.player === self) ?? false)
      : (skill.data?.rows.some((row) => row.player === self && row.eligible) ??
        false);

  const pick = (next: Board): void => {
    void navigate({
      to: "/leaderboard",
      search:
        next === "skill"
          ? { ...search, board: "skill" }
          : search.day === undefined
            ? {}
            : { day: search.day },
      replace: true,
    });
  };
  const goDay = (next: string): void => {
    // The newest day is the board with no day in the path.
    void navigate({
      to: "/leaderboard",
      search: next === revealed[0] ? {} : { day: next },
      replace: true,
    });
  };

  return (
    <div className="board">
      <BoardSky />
      <header className="board-head">
        <div className="board-title">
          <h1 className="h-display">Leaderboard</h1>
          {board === "skill" ? (
            <p className="board-sub">The skill ranking across many days.</p>
          ) : day === undefined ? null : (
            <p className="board-sub">
              <time dateTime={day}>{names.long(day)}</time>
              {count === undefined
                ? null
                : ` · ${count} ${count === 1 ? "player" : "players"}`}
              {code === undefined ? null : (
                <>
                  {" · code "}
                  <span className="code board-code">{code}</span>
                </>
              )}
            </p>
          )}
        </div>
        <div className="board-bar">
          {board === "day" && day !== undefined ? (
            <BoardDays day={day} days={revealed} onGo={goDay} />
          ) : null}
          <div className="board-tabs" role="tablist" aria-label="Which board">
            {TABS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                id={tabId(key)}
                className="board-tab"
                aria-selected={board === key}
                aria-controls="board-panel"
                tabIndex={board === key ? 0 : -1}
                onClick={() => pick(key)}
                onKeyDown={(event) => {
                  if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                    const next: Board = key === "day" ? "skill" : "day";
                    pick(next);
                    document.getElementById(tabId(next))?.focus();
                  }
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {findable ? (
            <button
              type="button"
              className="board-find"
              onClick={() => findOwnRow(panel.current, self)}
            >
              Find me
            </button>
          ) : null}
        </div>
      </header>
      <div
        id="board-panel"
        className="board-panel"
        role="tabpanel"
        aria-labelledby={tabId(board)}
        ref={panel}
      >
        {board === "day" ? (
          <DayPanel
            view={daily.data}
            named={search.day !== undefined}
            self={self}
            pending={daily.isPending}
            error={daily.isError ? daily.error : null}
          />
        ) : (
          <SkillPanel
            view={skill.data}
            self={self}
            pending={skill.isPending}
            error={skill.isError ? skill.error : null}
          />
        )}
      </div>
    </div>
  );
}

/**
 * Brings the caller's own row into view, and lights it for a moment.
 * The row is the place on the podium, a row of the table, or a row of
 * the ranked table: each carries the player in `data-player`.
 */
function findOwnRow(panel: HTMLElement | null, self: string): void {
  const own = [
    ...(panel?.querySelectorAll<HTMLElement>("[data-player]") ?? []),
  ].find((each) => each.dataset.player === self);
  if (own === undefined) {
    return;
  }
  const still =
    typeof window.matchMedia === "function" &&
    window.matchMedia(REDUCED_MOTION).matches;
  own.scrollIntoView({ block: "center", behavior: still ? "auto" : "smooth" });
  // An animation and not a class: React owns the class of the row.
  if (typeof own.animate === "function") {
    own.animate(
      [
        { backgroundColor: "rgba(143, 174, 255, 0.24)", offset: 0 },
        { backgroundColor: "rgba(143, 174, 255, 0.24)", offset: 0.4 },
        { backgroundColor: "transparent", offset: 1 },
      ],
      { duration: 1600, easing: "ease-out" },
    );
  }
}

/** The quiet sky behind the head of the page: a picture of stars. */
function BoardSky(): React.JSX.Element {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  useEffect(() => {
    if (canvas.current === null) {
      return;
    }
    const sky = createQuietSky(canvas.current, seedOf("leaderboard"));
    return () => sky.dispose();
  }, []);
  return (
    <div className="board-sky" aria-hidden="true">
      <canvas className="board-sky-field" ref={canvas} />
    </div>
  );
}

/**
 * The row of revealed days: the arrows step one day, and the date
 * opens a calendar of each revealed day, as on the Play screen.
 */
function BoardDays(props: {
  day: string;
  /** The revealed days, the newest first. */
  days: ReadonlyArray<string>;
  onGo: (day: string) => void;
}): React.JSX.Element {
  const { day, days } = props;
  const names = useDayNames();
  const [open, setOpen] = useState(false);
  const frame = useRef<HTMLDivElement | null>(null);
  const dateButton = useRef<HTMLButtonElement | null>(null);
  const calendarId = useId();
  useCalendarClose(open, setOpen, frame, dateButton);

  const at = days.indexOf(day);
  const before = at < 0 ? undefined : days[at + 1];
  const after = at > 0 ? days[at - 1] : undefined;
  const go = (next: string): void => {
    setOpen(false);
    props.onGo(next);
  };
  const cells = new Map<string, CalendarDay>();
  for (const each of days) {
    const date = names.calendarDate(each);
    if (date !== null) {
      cells.set(dateKey(date), { day: each, date, name: names.long(each) });
    }
  }
  const shown = names.calendarDate(day);

  return (
    <div className="day-stepper board-days" ref={frame}>
      <button
        type="button"
        className="btn btn-secondary day-step"
        aria-label="The day before"
        disabled={before === undefined}
        onClick={() => {
          if (before !== undefined) {
            go(before);
          }
        }}
      >
        <CaretLeft size={18} aria-hidden="true" />
      </button>
      <button
        type="button"
        ref={dateButton}
        className="day-date"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? calendarId : undefined}
        disabled={shown === null || at < 0}
        onClick={() => setOpen((old) => !old)}
      >
        <strong>{names.long(day)}</strong>
        <CalendarBlank size={16} aria-hidden="true" />
      </button>
      <button
        type="button"
        className="btn btn-secondary day-step"
        aria-label="The day after"
        disabled={after === undefined}
        onClick={() => {
          if (after !== undefined) {
            go(after);
          }
        }}
      >
        <CaretRight size={18} aria-hidden="true" />
      </button>
      {open && shown !== null ? (
        <div id={calendarId}>
          <Calendar
            days={cells}
            shown={dateKey(shown)}
            start={monthOf(shown)}
            note="Each revealed day has a board."
            onPick={(picked) => {
              if (picked !== null) {
                go(picked);
              }
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

function DayPanel(props: {
  view: LeaderboardView | undefined;
  /** True when the path names the day. */
  named: boolean;
  self: string;
  pending: boolean;
  error: unknown;
}): React.JSX.Element {
  const { view, pending, error } = props;
  if (pending) {
    return <p className="subtle">Loading…</p>;
  }
  if (view === undefined) {
    return isRefusal(error) ? (
      <p className="muted board-empty">
        {props.named
          ? "That day isn't revealed, so it has no board yet."
          : "No day has been revealed yet. This board fills in after the first one."}
      </p>
    ) : (
      <div className="notice notice-bad" role="alert">
        {friendlyMessage(error)}
      </div>
    );
  }
  return <DayBoard view={view} self={props.self} />;
}

function SkillPanel(props: {
  view: SkillBoardView | undefined;
  self: string;
  pending: boolean;
  error: unknown;
}): React.JSX.Element {
  const { view, self, pending, error } = props;
  if (pending) {
    return <p className="subtle">Loading…</p>;
  }
  if (view === undefined) {
    return (
      <div className="notice notice-bad" role="alert">
        {friendlyMessage(error)}
      </div>
    );
  }
  return (
    <>
      {/* Two columns on a wide screen. On a phone the two wrappers let
          go, and each section takes its place by its order
          (styles/board.css). */}
      <div className="board-grid">
        <div className="board-main">
          <SkillBoard view={view} self={self} />
        </div>
        <div className="board-side">
          <Population
            population={view.population}
            variation={view.variation}
            discovery={view.discovery}
          />
        </div>
      </div>
      {view.active ? <RankedPlayers view={view} self={self} /> : null}
    </>
  );
}

/**
 * The board name cell (D5 as ruled 2026-08-21): the avatar beside
 * the username, which is the one name of a player (spec A2 ruling
 * 3). The circle falls back to initials, so a board with no pictures
 * reads as it did before the ruling.
 */
function PlayerCell(props: {
  player: string;
  avatarHash: string | null;
  /** Absent on the skill board: its rows hold no streak (spec H1 §10). */
  streak?: number;
  self: string;
  /**
   * True where the row has no room for the circle: the ranked table on
   * a phone, where the name, the range, and two numbers need the width.
   */
  bare?: boolean;
}): React.JSX.Element {
  const { player, avatarHash, streak = 0, self } = props;
  return (
    <span className="board-player">
      {props.bare === true ? null : (
        <AvatarCircle
          player={player}
          avatarHash={avatarHash}
          size={28}
          streak={streak}
        />
      )}
      {/* The full name stays for a pointer and for assistive technology:
          on a phone the cell shortens a long name so the numbers of the
          row stay on the screen. */}
      <span
        className="player-name"
        title={player === self ? undefined : player}
      >
        <StreakName streak={streak}>
          {player === self ? "You" : player}
        </StreakName>
      </span>
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
  const own = view.rows.find((row) => row.player === self) ?? null;
  return (
    <>
      <section className="card board-skill" aria-labelledby="skill-heading">
        <h2 id="skill-heading">Skill ranking</h2>
        <p className="muted small">
          Each star is a player: their skill number against how many results
          they've sent.
        </p>
        {view.provisional ? <Provisional view={view} /> : null}
        <Funnel view={view} self={self} />
        <Legend />
      </section>
      {own !== null && !own.eligible ? (
        <NotYetRanked row={own} floor={view.eligibility_floor} />
      ) : null}
      {own?.eligible ? <OwnEvidence row={own} /> : null}
    </>
  );
}

/** The ranked table, at the full width of the page. */
function RankedPlayers(props: {
  view: SkillBoardView;
  self: string;
}): React.JSX.Element {
  const [limit, setLimit] = useState(TABLE_LIMIT);
  const slice = boardSlice(props.view.rows, props.self, limit);
  const more = slice.total > slice.shown.length;
  return (
    <section className="card board-ranked" aria-labelledby="ranked-heading">
      <div className="board-heading">
        <h2 id="ranked-heading">Ranked players</h2>
        {more ? (
          <span>
            Showing {slice.shown.length} of {slice.total.toLocaleString()}{" "}
            ranked players.
          </span>
        ) : null}
      </div>
      <RankedTable slice={slice} self={props.self} />
      <div className="board-ranked-foot">
        {more ? (
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setLimit((old) => old + TABLE_STEP)}
          >
            Show more players
          </button>
        ) : null}
        <p className="hint">
          Place is an estimate, so it can be a fraction, and the likely range is
          where a player's true place probably falls. Steadied skill stays near
          the middle until enough results back it, so it can differ from the
          plain number on your results page. The hit number is shown and not
          ranked: it rewards occasional strong hits, where the skill number
          rewards a steady edge.
        </p>
      </div>
    </section>
  );
}

function GatedBoard(props: { view: SkillBoardView }): React.JSX.Element {
  const { view } = props;
  return (
    <section className="card board-skill" aria-labelledby="skill-heading">
      <h2 id="skill-heading">Skill ranking</h2>
      <p className="board-claim">
        The skill ranking starts once a player has sent {view.eligibility_floor}{" "}
        results. Nobody has yet.
      </p>
      <p className="muted">
        A ranking needs that many results behind each number to mean anything.
        Until then, each day's results are under The day. After {view.fit_floor}{" "}
        players reach {view.eligibility_floor} results, the ranking stops being
        provisional.
      </p>
    </section>
  );
}

function Provisional(props: { view: SkillBoardView }): React.JSX.Element {
  const { view } = props;
  return (
    <p className="muted small" role="note">
      Provisional — fewer than {view.fit_floor} players have{" "}
      {view.eligibility_floor} results ({view.eligible_count} so far), so the
      ranking assumes a typical spread between players instead of measuring it.
    </p>
  );
}

/**
 * The least distance between two labels of the skill scale, in viewBox
 * units: a label nearer than this to a kept label would cover it.
 */
const LABEL_GAP = 16;

/**
 * The labels of the skill scale that have room. The label of chance
 * comes first, then each other label from the nearest to chance to the
 * farthest, and a label that would cover a kept one is left out. The
 * stars and the band do not move: this drops words, not data.
 */
function spacedTicks(
  ticks: ReadonlyArray<AxisTick>,
  at: (position: number) => number,
): AxisTick[] {
  const kept: AxisTick[] = [];
  const byChance = [...ticks].sort(
    (a, b) => Math.abs(Math.log(a.value)) - Math.abs(Math.log(b.value)),
  );
  for (const tick of byChance) {
    const y = at(tick.position);
    if (kept.every((other) => Math.abs(at(other.position) - y) >= LABEL_GAP)) {
      kept.push(tick);
    }
  }
  return kept;
}

/**
 * The star chart. Each player is a star: a ring before the ranking
 * floor, a bright star after it, and the caller's own star in the
 * accent color with a halo. The band is one filled shape with no
 * edge line, and the line of chance is the one dashed line: a dashed
 * edge on the band reads as a threshold, and there is no threshold
 * anywhere on this chart.
 */
function Funnel(props: {
  view: SkillBoardView;
  self: string;
}): React.JSX.Element {
  const { view, self } = props;
  const narrow = useNarrow();
  const plot = narrow ? NARROW_PLOT : WIDE_PLOT;
  const geometry = funnelGeometry(view.rows, view.baseline_band, self);
  if (geometry.empty) {
    return <p className="muted">No players to draw yet.</p>;
  }
  const width = plot.width - plot.left - plot.right;
  const height = plot.height - plot.top - plot.bottom;
  const base = plot.top + height;
  const px = (x: number): number => plot.left + x * width;
  const py = (y: number): number => plot.top + y * height;
  // The band as one closed shape: along the top edge, back along
  // the bottom.
  const outline = [
    ...geometry.band.map((edge) => `${px(edge.x)},${py(edge.top)}`),
    ...[...geometry.band]
      .reverse()
      .map((edge) => `${px(edge.x)},${py(edge.bottom)}`),
  ].join(" ");
  const chance = geometry.skillTicks.find((tick) => tick.value === 1);
  const own = geometry.points.find((point) => point.self);
  // The caller's name sits after the star, or before it near the
  // right edge.
  const ownBefore = own !== undefined && px(own.x) > plot.width - 70;
  return (
    <figure className="board-chart">
      <svg
        viewBox={`0 0 ${plot.width} ${plot.height}`}
        role="img"
        aria-label={
          `Skill number against results sent for ${geometry.points.length} ` +
          "players, with the range play with no skill produces at each count."
        }
      >
        <title>Skill number against results sent</title>
        {geometry.band.length > 1 ? (
          <polygon className="board-chart-band" points={outline} />
        ) : null}
        <g className="board-chart-scale">
          {spacedTicks(geometry.skillTicks, py).map((tick) => (
            <text key={`skill-${tick.value}`} x={0} y={py(tick.position) + 4}>
              {tick.label}
            </text>
          ))}
          {geometry.trialTicks.map((tick) => (
            <text
              key={`trials-${tick.value}`}
              x={px(tick.position)}
              y={base + 22}
              textAnchor="middle"
            >
              {tick.label}
            </text>
          ))}
        </g>
        <line
          className="board-chart-base"
          x1={plot.left - 16}
          x2={plot.width}
          y1={base}
          y2={base}
        />
        {chance === undefined ? null : (
          <line
            className="board-chart-chance"
            x1={plot.left - 16}
            x2={plot.width}
            y1={py(chance.position)}
            y2={py(chance.position)}
          />
        )}
        <g className="board-chart-label">
          <text x={plot.width} y={plot.height - 4} textAnchor="end">
            results sent
          </text>
          {narrow || chance === undefined ? null : (
            <text x={plot.width} y={py(chance.position) + 18} textAnchor="end">
              chance
            </text>
          )}
        </g>
        {own === undefined ? null : (
          <circle
            className="board-chart-halo"
            cx={px(own.x)}
            cy={py(own.y)}
            r={narrow ? 10 : 12}
          />
        )}
        {geometry.points.map((point) => (
          <circle
            key={point.player}
            className={
              point.self
                ? "board-star is-you"
                : point.eligible
                  ? "board-star"
                  : "board-star is-unranked"
            }
            cx={px(point.x)}
            cy={py(point.y)}
            r={point.self ? 5 : point.eligible ? 3 : 2.6}
          >
            {/* An SVG title is an element. The HTML title attribute
                does not carry over. */}
            <title>
              {point.self ? "You" : point.player} — skill number{" "}
              {point.theta.toFixed(2)} after {point.n}{" "}
              {point.n === 1 ? "result" : "results"}
              {point.eligible ? "" : " (not ranked yet)"}
            </title>
          </circle>
        ))}
        {own === undefined ? null : (
          <text
            className="board-chart-you"
            x={ownBefore ? px(own.x) - 16 : px(own.x) + 16}
            y={py(own.y) - 4}
            textAnchor={ownBefore ? "end" : "start"}
          >
            You
          </text>
        )}
      </svg>
    </figure>
  );
}

function Legend(): React.JSX.Element {
  return (
    <>
      <ul className="board-key" aria-label="Key">
        <li>
          <span className="board-key-mark is-you" aria-hidden="true" />
          You
        </li>
        <li>
          <span className="board-key-mark" aria-hidden="true" />
          Ranked
        </li>
        <li>
          <span className="board-key-mark is-unranked" aria-hidden="true" />
          Not ranked yet
        </li>
      </ul>
      <p className="muted small board-key-note">
        The line at 1.00 is chance, the same thing as averaging 50%. Stars show
        the plain skill number. The shaded band is where players with no skill
        land. It narrows to the right because more results pin a number down —
        so a high star on the left means less than a high star on the right.
      </p>
    </>
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
    <section className="card board-own" aria-labelledby="evidence-heading">
      <h2 id="evidence-heading">How unusual your results are</h2>
      <p className="board-claim">
        {evidenceSentence(row.anytime_significance)}
      </p>
      <p className="muted">
        This holds however often you check and whenever you stop. Put another
        way: a fair bet against pure luck would have turned 1 point into{" "}
        {evidenceE(row)} points.
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
    <section className="card board-own" aria-labelledby="standing-heading">
      <h2 id="standing-heading">Where you stand</h2>
      <p className="board-claim">
        You've sent {row.n} of the {floor} results a ranking needs.
      </p>
      <p className="muted">
        Your star is on the chart already. Until {floor} results, the range
        around it is too wide for a place on the board to mean much.
      </p>
    </section>
  );
}

function RankedTable(props: {
  slice: ReturnType<typeof boardSlice>;
  self: string;
}): React.JSX.Element {
  const { slice, self } = props;
  const narrow = useNarrow();
  // A phone has room for four columns: the range and the result count
  // go under the name, at the size and the color of the name.
  const columns = narrow ? 4 : 6;
  return (
    <div className="table-scroll">
      <table className="table board-table" data-testid="ranked-table">
        <thead>
          <tr>
            <th scope="col" className="num">
              Place
            </th>
            <th scope="col">{narrow ? "Player and likely range" : "Player"}</th>
            <th scope="col" className="num">
              Steadied skill
            </th>
            <th scope="col" className="num">
              Hit number
            </th>
            {narrow ? null : (
              <>
                <th scope="col" className="board-range-head">
                  Likely range of place, 1 to {slice.total.toLocaleString()}
                </th>
                <th scope="col" className="num">
                  Results
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {slice.shown.map((row) => (
            <RankedRow
              key={row.player}
              row={row}
              self={self}
              total={slice.total}
              narrow={narrow}
            />
          ))}
          {slice.pinned === null ? null : (
            <>
              <tr className="board-gap">
                <td colSpan={columns} />
              </tr>
              <RankedRow
                row={slice.pinned}
                self={self}
                total={slice.total}
                narrow={narrow}
              />
            </>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Where a place sits on the line from 1 to the count, in percent. */
function placeAt(place: number, total: number): number {
  return total <= 1
    ? 0
    : Math.max(0, Math.min(100, ((place - 1) / (total - 1)) * 100));
}

/**
 * The likely range of a place as a drawing: the line is each place
 * from 1 to the count of ranked players, the bar is the range, and
 * the star is the place. It draws the three numbers of the row and
 * adds none.
 */
function RangeBar(props: {
  row: SkillBoardRow;
  total: number;
}): React.JSX.Element | null {
  const { row, total } = props;
  if (
    row.rank_low === null ||
    row.rank_high === null ||
    row.expected_rank === null
  ) {
    return null;
  }
  const low = placeAt(row.rank_low, total);
  const high = placeAt(row.rank_high, total);
  return (
    <span className="board-range-bar" aria-hidden="true">
      <span
        className="board-range-span"
        style={{ left: `${low}%`, width: `${high - low}%` }}
      />
      <span
        className="board-range-star"
        style={{ left: `${placeAt(row.expected_rank, total)}%` }}
      />
    </span>
  );
}

function RankedRow(props: {
  row: SkillBoardRow;
  self: string;
  total: number;
  narrow: boolean;
}): React.JSX.Element {
  const { row, self, total, narrow } = props;
  const mine = row.player === self;
  const range = `${row.rank_low ?? "—"} to ${row.rank_high ?? "—"}`;
  // The rank, the range, and the result count carry equal weight
  // (spec M1 §9): no muted colour and no smaller size on any of them.
  return (
    <tr className={mine ? "is-you" : undefined} data-player={row.player}>
      {/* Fractional: a posterior expectation, not a position. */}
      <td className="num">{row.expected_rank?.toFixed(1) ?? "—"}</td>
      <td>
        <PlayerCell
          player={row.player}
          avatarHash={row.avatar_hash}
          self={self}
          bare={narrow}
        />
        {narrow ? (
          <span className="board-under">
            {range}, from {row.n} {row.n === 1 ? "result" : "results"}
          </span>
        ) : null}
      </td>
      <td className="num">
        {row.shrunk === null ? "—" : Math.exp(row.shrunk).toFixed(2)}
      </td>
      <td className="num">{row.hit_number.toFixed(2)}</td>
      {narrow ? null : (
        <>
          <td>
            <span className="board-range">
              <span className="board-range-text">{range}</span>
              <RangeBar row={row} total={total} />
            </span>
          </td>
          <td className="num">{row.n}</td>
        </>
      )}
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
    <section className="card board-all" aria-labelledby="population-heading">
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
        <p className="muted">
          {discovery.flagged} of {discovery.tested} players stand out above
          chance. About {discovery.expected_by_luck.toFixed(1)} of those would
          stand out by luck alone.
        </p>
      )}
      {variation === null ? null : (
        <details className="row-disclosure board-numbers">
          <summary>
            The numbers
            <span className="row-meta">
              <CaretRight
                size={16}
                aria-hidden="true"
                className="row-chevron"
              />
            </span>
          </summary>
          <div className="row-body">
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
                    Score {variation.q_statistic.toFixed(1)}, and luck alone
                    gives about {variation.dof}. Chance of this by luck:{" "}
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
