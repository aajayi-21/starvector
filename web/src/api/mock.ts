/**
 * The deterministic mock adapter (spec W1 §7). Serves the surfaces
 * the backend does not have yet, plus a full-mock mode for offline
 * UI work. Every value derives from a keyed hash — no Math.random,
 * no clock — so two instances built with the same options answer
 * byte-identically.
 */

import type { Api } from "./client";
import type {
  BaselineBandPoint,
  DayView,
  HistoryDayRow,
  HistoryView,
  LeaderboardRow,
  LeaderboardView,
  MeView,
  PracticeDays,
  PracticeScore,
  RankingHeadRow,
  ReportRow,
  RevealView,
  SkillBoardRow,
  SkillBoardView,
  StoredSubmission,
  SubmissionAck,
  TrialValue,
  WireRecord,
  WireStroke,
} from "./types";
import { ApiError } from "./types";

const DECOY_COUNT = 119;
const CODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const HEX_ALPHABET = "0123456789abcdef";
const CAST = [
  "marlow",
  "quietsignal",
  "hollis-r",
  "vetiver",
  "iris-v",
  "tallgrass",
];
const ATOM_BANK: ReadonlyArray<readonly [string, string | null]> = [
  ["tall vertical structure", "lighthouse tower"],
  ["water nearby", "sea"],
  ["cold", null],
  ["curved edge", "arch"],
  ["small bright shape", "lantern"],
];

function fnv1a(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** One draw in [0, 1), a pure function of the key. */
function draw(key: string): number {
  let state = fnv1a(key) + 0x6d2b79f5;
  state = Math.imul(state ^ (state >>> 15), state | 1);
  state ^= state + Math.imul(state ^ (state >>> 7), state | 61);
  return ((state ^ (state >>> 14)) >>> 0) / 4294967296;
}

function round4(value: number): number {
  return Math.round(value * 1e4) / 1e4;
}

function fromAlphabet(key: string, alphabet: string, length: number): string {
  let out = "";
  for (let index = 0; index < length; index += 1) {
    const pick = Math.floor(draw(`${key}:${index}`) * alphabet.length);
    out += alphabet.charAt(pick);
  }
  return out;
}

const seededHex = (key: string, length: number): string =>
  fromAlphabet(key, HEX_ALPHABET, length);
const seededCode = (key: string): string => fromAlphabet(key, CODE_ALPHABET, 6);

/** day ± n in calendar days, UTC, YYYY-MM-DD in and out. */
function shiftDay(day: string, byDays: number): string {
  const epoch = Date.parse(`${day}T00:00:00Z`);
  const shifted = new Date(epoch + byDays * 86_400_000);
  return shifted.toISOString().slice(0, 10);
}

function trialFor(seed: string): TrialValue {
  // The system of record pins p = (beaten + 0.5 * tied) / decoy_count
  // (core/ranking.py); with tied 0 the identity must hold exactly.
  const beaten = 1 + Math.floor(draw(`p:${seed}`) * (DECOY_COUNT - 1));
  return {
    p: beaten / DECOY_COUNT,
    decoy_count: DECOY_COUNT,
    beaten,
    tied: 0,
    target_rank: DECOY_COUNT - beaten + 1,
  };
}

function reportFor(seed: string, count: number): ReportRow[] {
  const rows: ReportRow[] = [];
  for (let index = 0; index < count; index += 1) {
    const bankRow = ATOM_BANK[index % ATOM_BANK.length];
    if (bankRow === undefined) {
      break;
    }
    const [atomText, element] = bankRow;
    rows.push({
      atom_id: `a${index + 1}`,
      atom_text: atomText,
      element,
      weight: round4(0.1 + 0.3 * draw(`${seed}:w:${index}`)),
      similarity: round4(0.3 + 0.6 * draw(`${seed}:s:${index}`)),
      rarity: Math.round(100 * (0.8 + draw(`${seed}:r:${index}`))) / 100,
    });
  }
  return rows;
}

export interface MockOptions {
  /** The anchor day — fixed so tests are byte-stable. */
  today?: string;
  player?: string;
}

// ── spec M1: a synthetic population for the skill board ─────────
//
// CAST is six names and cannot make a funnel. These players come
// from the same keyed hash the rest of the mock uses: no
// Math.random and no clock, thus two loads give equal bytes.

const POPULATION = 140;
const MOCK_ELIGIBILITY_FLOOR = 30;
const MOCK_FIT_FLOOR = 30;
const MOCK_MU = 0.06;
const MOCK_TAU = 0.18;
const STEM_A = [
  "quiet",
  "tall",
  "north",
  "slow",
  "amber",
  "pale",
  "far",
  "still",
];
const STEM_B = [
  "signal",
  "grass",
  "harbor",
  "vetiver",
  "iris",
  "hollis",
  "marlow",
  "ember",
];

/**
 * The two evidence fields, kept consistent with each other.
 *
 * The live pair comes from one closed form (spec M1 §6) that a
 * mock has no business reimplementing — a Layer 9 formula lives
 * in one place. So the mock draws the significance and derives
 * the e-value from it. What matters here is that the two agree:
 * a screen that renders one from the other must not meet a row
 * where they disagree.
 */
function significanceOf(drawn: number): {
  log_e_value: number;
  anytime_significance: number;
} {
  const significance = Math.min(1, Math.max(1e-6, drawn));
  return {
    log_e_value: round4(-Math.log(significance)),
    anytime_significance: round4(significance),
  };
}

/** A standard normal from two keyed draws - Box-Muller, pure. */
function normalDraw(key: string): number {
  const first = Math.max(draw(`${key}:u`), 1e-12);
  return (
    Math.sqrt(-2 * Math.log(first)) * Math.cos(2 * Math.PI * draw(`${key}:v`))
  );
}

/**
 * The synthetic board.
 *
 * The trial count is log-uniform on [3, 400]: a straight draw puts
 * almost every player past the eligibility floor and the funnel's
 * mouth stays empty. The observed value carries the observation
 * error the no-skill law predicts, thus the scatter genuinely
 * narrows as the trial count rises and the bands genuinely contain
 * it.
 *
 * 140 players across a 64-name space generates duplicate display
 * names on its own, thus the shared-label case is exercised
 * without being planted, while the store keys stay unique.
 */
function skillBoard(player: string, ownScore: number): SkillBoardView {
  const rows: SkillBoardRow[] = [];
  for (let index = 0; index < POPULATION; index += 1) {
    const n = Math.max(
      3,
      Math.round(3 * Math.exp(draw(`pop:n:${index}`) * Math.log(400 / 3))),
    );
    const logTheta =
      MOCK_MU +
      MOCK_TAU * normalDraw(`pop:t:${index}`) +
      normalDraw(`pop:e:${index}`) / Math.sqrt(n);
    const first = STEM_A[Math.floor(draw(`pop:a:${index}`) * STEM_A.length)];
    const second = STEM_B[Math.floor(draw(`pop:b:${index}`) * STEM_B.length)];
    rows.push({
      player: `${first}-${second}-${index}`,
      display_name: `${first} ${second}`,
      n,
      eligible: n >= MOCK_ELIGIBILITY_FLOOR,
      theta: round4(Math.exp(logTheta)),
      shrunk: null,
      y: round4(logTheta),
      v: round4(1 / n),
      expected_rank: null,
      rank_low: null,
      rank_high: null,
      evidence_p: round4(draw(`pop:p:${index}`)),
      ...significanceOf(draw(`pop:s:${index}`)),
    });
  }
  rows.unshift({
    player,
    display_name: player,
    n: 61,
    eligible: true,
    theta: round4(Math.exp(MOCK_MU + 0.31)),
    shrunk: null,
    y: round4(MOCK_MU + 0.31),
    v: round4(1 / 61),
    expected_rank: null,
    rank_low: null,
    rank_high: null,
    evidence_p: round4(ownScore),
    ...significanceOf(0.041),
  });

  // Ruling 17 of 2026-08-16: every player holds a row and the
  // eligible ones hold a rank. The ranking runs over the eligible
  // rows alone, thus the low-trial scatter cannot move anybody's
  // rank - the rule the server follows.
  const eligible = rows.filter((row) => row.eligible);
  const rest = rows.filter((row) => !row.eligible);
  eligible.sort((a, b) => b.y - a.y);
  const middle = (eligible.length + 1) / 2;
  eligible.forEach((row, position) => {
    const weight = row.n / (row.n + 1 / (MOCK_TAU * MOCK_TAU));
    // The shrunk estimate pulls toward the population centre, thus
    // the table's number and the chart's dot are not the same
    // number - which is the point of plotting the raw estimate.
    row.shrunk = round4(MOCK_MU + (row.y - MOCK_MU) * weight);
    // The posterior expected rank pulls a low-trial player toward
    // the middle (spec M1 §6). The mock reproduces the direction
    // with the shrinkage weight and not the simulation.
    const rank = round4(weight * (position + 1) + (1 - weight) * middle);
    const half = Math.max(
      1,
      Math.round((1 - weight) * eligible.length * 0.5 + 2),
    );
    row.expected_rank = rank;
    row.rank_low = Math.max(1, Math.round(rank) - half);
    row.rank_high = Math.min(eligible.length, Math.round(rank) + half);
  });
  eligible.sort((a, b) => (a.expected_rank ?? 0) - (b.expected_rank ?? 0));
  rest.sort((a, b) => b.n - a.n);
  const ordered = [...eligible, ...rest];

  const mean =
    eligible.reduce((total, row) => total + row.y, 0) / eligible.length;
  // Computed from the generated rows, thus the reported number
  // agrees with the dots a chart paints.
  const statistic = eligible.reduce(
    (total, row) => total + (row.y - mean) ** 2 / row.v,
    0,
  );
  const band: BaselineBandPoint[] = [];
  for (let step = 0; step < 12; step += 1) {
    // 1.96/sqrt(n) here. The live server uses sqrt(trigamma(n))
    // (core/aggregate.py) - this is the mock's data-generator
    // stand-in and not a published number.
    const n = Math.round(3 * Math.exp((step / 11) * Math.log(400 / 3)));
    band.push({
      n,
      low: round4(MOCK_MU - 1.96 / Math.sqrt(n)),
      high: round4(MOCK_MU + 1.96 / Math.sqrt(n)),
    });
  }
  const flagged = eligible.filter((row) => row.evidence_p <= 0.05).length;
  return {
    active: eligible.length >= 1,
    player_count: ordered.length,
    eligible_count: eligible.length,
    degenerate_count: 0,
    eligibility_floor: MOCK_ELIGIBILITY_FLOOR,
    recomputed_floor: null,
    fit_floor: MOCK_FIT_FLOOR,
    provisional: eligible.length < MOCK_FIT_FLOOR,
    rows: ordered,
    baseline_band: band,
    population: {
      mu: round4(MOCK_MU),
      tau: round4(MOCK_TAU),
      mu_spread: round4(MOCK_TAU / Math.sqrt(eligible.length)),
      fitted: true,
      halvings: 60,
    },
    variation: {
      q_statistic: round4(statistic),
      dof: eligible.length - 1,
      q_significance: 0.0001,
      tau_low: round4(MOCK_TAU * 0.86),
      tau_high: round4(MOCK_TAU * 1.19),
      tau_multiplicative: round4(Math.exp(MOCK_TAU)),
      prediction_low: round4(MOCK_MU - 1.96 * MOCK_TAU),
      prediction_high: round4(MOCK_MU + 1.96 * MOCK_TAU),
    },
    discovery: {
      level: 0.05,
      tested: eligible.length,
      flagged,
      expected_by_luck: round4(0.05 * flagged),
    },
  };
}

export function makeMockApi(options: MockOptions = {}): Api {
  const today = options.today ?? "2026-08-14";
  const player = options.player ?? "ade";

  /** The 30 days before today, newest first, ~70% played. */
  const playedDays: string[] = [];
  for (let back = 1; back <= 30; back += 1) {
    const day = shiftDay(today, -back);
    if (draw(`played:${day}`) < 0.7) {
      playedDays.push(day);
    }
  }
  const playedSet = new Set(playedDays);

  function historyDays(): HistoryDayRow[] {
    return playedDays.map((day) => {
      const trial = trialFor(day);
      return {
        day,
        trial_code: seededCode(`code:${day}`),
        p: trial.p,
        target_rank: trial.target_rank,
        decoy_count: trial.decoy_count,
      };
    });
  }

  /**
   * §7's definition: the count of days in an unbroken calendar run
   * that ends at the newest revealed day, each with a stored
   * submission.
   */
  function streak(): number {
    const newest = playedDays[0];
    if (newest === undefined) {
      return 0;
    }
    let count = 0;
    let cursor = newest;
    while (playedSet.has(cursor)) {
      count += 1;
      cursor = shiftDay(cursor, -1);
    }
    return count;
  }

  function targetId(day: string): string {
    return seededHex(`target:${day}`, 64);
  }

  function revealFor(day: string): RevealView {
    return {
      day,
      target_id: targetId(day),
      secret: seededHex(`secret:${day}`, 64),
      commitment: seededHex(`commitment:${day}`, 64),
      check: "printf '%s:%s' TARGET SECRET | sha256sum",
      trial: trialFor(day),
      report: reportFor(`report:${day}`, 4),
    };
  }

  // Full-mock in-memory day state (offline UI work only).
  let submittedToday = false;

  return {
    // ── §6 surfaces: reachable only in full-mock mode ──────────
    getDay(): Promise<DayView> {
      return Promise.resolve({
        day: today,
        trial_code: seededCode(`code:${today}`),
        status: "open",
        commitment: seededHex(`commitment:${today}`, 64),
        player,
        submitted: submittedToday,
        relation_vocabulary: ["left-of", "right-of", "above", "below"],
        canvas_px: 512,
        closes_at: null,
      });
    },
    submit(record: WireRecord): Promise<SubmissionAck> {
      if (submittedToday) {
        return Promise.reject(new ApiError(409, "already-submitted"));
      }
      submittedToday = true;
      const labeled = record.groups.filter((g) => g.label !== "").length;
      const atomCount =
        record.impressions.length +
        labeled +
        record.relations.length +
        (record.canvas_strokes.length > 0 ? 1 : 0) +
        (record.pasted_text !== null ? 1 : 0);
      return Promise.resolve({
        trial_id: seededHex(`trial:${today}`, 32),
        atom_count: atomCount,
      });
    },
    getReveal(day?: string): Promise<RevealView> {
      // A named day is served for the same reason as the
      // leaderboard; the no-argument (latest) path keeps the
      // constant refusal when nothing is played.
      if (day !== undefined) {
        return Promise.resolve(revealFor(day));
      }
      const target = playedDays[0];
      if (target === undefined) {
        return Promise.reject(new ApiError(404, undefined, "not revealed"));
      }
      return Promise.resolve(revealFor(target));
    },
    imageUrl(imageId: string): string {
      const label = imageId.slice(0, 8);
      const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">` +
        `<rect width="96" height="96" fill="#3b4252"/>` +
        `<text x="48" y="52" font-size="9" fill="#97a1b4" ` +
        `text-anchor="middle" font-family="monospace">${label}</text></svg>`;
      return `data:image/svg+xml,${encodeURIComponent(svg)}`;
    },
    getPracticeDays(): Promise<PracticeDays> {
      if (playedDays.length === 0) {
        return Promise.reject(new ApiError(404, undefined, "no revealed day"));
      }
      return Promise.resolve({
        days: playedDays.map((day) => ({
          day,
          target_id: targetId(day),
          trial_code: seededCode(`code:${day}`),
        })),
      });
    },
    scorePractice(day: string, record: WireRecord): Promise<PracticeScore> {
      if (!playedSet.has(day)) {
        return Promise.reject(
          new ApiError(404, undefined, "not a practice day"),
        );
      }
      const seed = `practice:${day}:${fnv1a(JSON.stringify(record))}`;
      const trial = trialFor(seed);
      const targetPosition = trial.target_rank;
      const head: RankingHeadRow[] = [];
      for (let position = 1; position <= 10; position += 1) {
        head.push({
          position,
          fused: round4(
            1.2 - 0.07 * position - 0.05 * draw(`${seed}:f:${position}`),
          ),
          is_target: position === targetPosition,
        });
      }
      return Promise.resolve({
        day,
        target_id: targetId(day),
        trial,
        target_position: targetPosition,
        ranking_head: head,
        report: reportFor(seed, Math.min(4, 1 + record.impressions.length)),
      });
    },

    // ── §7 surfaces: the contract, mock-served this phase ──────
    getHistory(): Promise<HistoryView> {
      const days = historyDays();
      if (days.length === 0) {
        return Promise.resolve({ days, skill: null });
      }
      const logOdds = days.map((row) => Math.log(row.p / (1 - row.p)));
      const mean = logOdds.reduce((a, b) => a + b, 0) / logOdds.length;
      const theta = Math.exp(mean);
      const shrunk = Math.exp((days.length / (days.length + 4)) * mean);
      // Illustrative proxy with the record's direction: the true
      // evidence_p (core/aggregate.py) is a tail probability where
      // SMALL means strong evidence. Chance sits near 0.5 here.
      const surprise = days
        .map((row) => -Math.log(row.p))
        .reduce((a, b) => a + b, 0);
      const evidence = Math.min(
        1,
        0.5 * Math.exp((surprise - days.length) / Math.sqrt(days.length)),
      );
      return Promise.resolve({
        days,
        skill: {
          theta: round4(theta),
          shrunk: round4(shrunk),
          evidence_p: round4(evidence),
          n: days.length,
        },
      });
    },
    getLeaderboard(named?: string): Promise<LeaderboardView> {
      // Any requested day is served: in composite mode the caller
      // holds a day the live server revealed, and the mock cannot
      // know the live revealed set — a gate here would kill the
      // card for real days (the backend phase adds the true
      // revealed-only 404).
      //
      // No day names the newest revealed one, as the server does.
      const day = named ?? playedDays[0];
      if (day === undefined) {
        return Promise.reject(new ApiError(404, undefined, "not revealed"));
      }
      const own = trialFor(day);
      const rows: LeaderboardRow[] = [
        {
          player,
          display_name: player,
          p: own.p,
          target_rank: own.target_rank,
          decoy_count: own.decoy_count,
          streak: streak(),
        },
      ];
      for (const name of CAST) {
        const trial = trialFor(`lb:${day}:${name}`);
        rows.push({
          player: name,
          display_name: name,
          p: trial.p,
          target_rank: trial.target_rank,
          decoy_count: trial.decoy_count,
          streak: 1 + Math.floor(21 * draw(`lbstreak:${day}:${name}`)),
        });
      }
      rows.sort((a, b) => b.p - a.p);
      return Promise.resolve({ day, rows });
    },
    getSubmission(day: string): Promise<StoredSubmission> {
      if (!playedSet.has(day)) {
        return Promise.reject(new ApiError(404, undefined, "no submission"));
      }
      const seed = `sub:${day}`;
      const strokes: WireStroke[] = [];
      for (let strokeIndex = 0; strokeIndex < 3; strokeIndex += 1) {
        const x0 = 0.15 + 0.6 * draw(`${seed}:x:${strokeIndex}`);
        const y0 = 0.15 + 0.6 * draw(`${seed}:y:${strokeIndex}`);
        const angle = 2 * Math.PI * draw(`${seed}:a:${strokeIndex}`);
        const points: [number, number][] = [];
        for (let step = 0; step < 8; step += 1) {
          const reach = 0.02 * step;
          points.push([
            round4(Math.min(1, Math.max(0, x0 + reach * Math.cos(angle)))),
            round4(Math.min(1, Math.max(0, y0 + reach * Math.sin(angle)))),
          ]);
        }
        const stroke: WireStroke = {
          points,
          group_id: strokeIndex === 0 ? "g1" : null,
        };
        if (strokeIndex === 1) {
          stroke.color = "#81a1c1";
        }
        strokes.push(stroke);
      }
      return Promise.resolve({
        trial_id: seededHex(`${seed}:trial`, 32),
        record: {
          impressions: ["tall vertical structure", "water nearby"],
          canvas_strokes: strokes,
          groups: [{ id: "g1", label: "tower" }],
          relations: [],
          pasted_text: null,
        },
      });
    },
    getSkillLeaderboard(): Promise<SkillBoardView> {
      return Promise.resolve(skillBoard(player, trialFor("skill:self").p));
    },
    getMe(): Promise<MeView> {
      return Promise.resolve({
        player,
        display_name: player,
        streak: streak(),
        reminder: false,
      });
    },
  };
}
