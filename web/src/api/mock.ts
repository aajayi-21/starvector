/**
 * The deterministic mock adapter (spec W1 §7). Serves the surfaces
 * the backend does not have yet, plus a full-mock mode for offline
 * UI work. Every value derives from a keyed hash — no Math.random,
 * no clock — so two instances built with the same options answer
 * byte-identically.
 */

import { NOTICE_VERSION } from "../signin/notice";
import {
  allOk,
  compactRecoveryCode,
  CODE_ALPHABET as DEVICE_ALPHABET,
  displayRecoveryCode,
  foldedName,
  normalizeUsername,
  passwordChecks,
  RECOVERY_CODE_LENGTH,
  usernameChecks,
} from "../signin/rules";
import type { Api } from "./client";
import type {
  AboutView,
  BaselineBandPoint,
  ConsentAck,
  DayView,
  DeviceCodeView,
  HistoryDayRow,
  HistoryView,
  LeaderboardRow,
  LeaderboardView,
  MeView,
  OperatorCodeView,
  PasswordAck,
  PracticeDays,
  PracticeScore,
  RankingHeadRow,
  RecoveryAck,
  RecoveryCodeAck,
  ReportRow,
  RevealView,
  SessionRow,
  SessionsView,
  SignInAck,
  SignupView,
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
  /**
   * False: a player from before spec A2, signed in with no password.
   * The account screen then offers "Set a password".
   */
  hasPassword?: boolean;
  /** A live operator's code, which lights the notice (spec A2 §6.1). */
  operatorCode?: OperatorCodeView | null;
  /** False: the mock starts signed out, at the gate screen. */
  signedIn?: boolean;
  /**
   * True: this mock server publishes results, thus a send needs the
   * agreement to the notice (spec R1 §3.3). The default is false, and
   * the offline flows then meet no notice screen.
   */
  noticeRequired?: boolean;
  /** True: the first player has agreed to the current notice. */
  noticeAgreed?: boolean;
  /** The mock server's notice version. The default is the screen's. */
  noticeVersion?: number;
  /** Where the mock's published snapshots are, or null for none. */
  publicDataUrl?: string | null;
}

/**
 * The password of the mock's first player. A mock value for offline
 * work and tests: no server holds it.
 */
export const MOCK_PASSWORD = "open sesame mock door";

/** The floor of the daily board (spec A2 §9.5, decision D12). */
const MOCK_BOARD_FLOOR_DAYS = 3;

/** Spec A2 decision D2, mirrored for the name-reserved refusal. */
const MOCK_RESERVED = new Set(
  [
    "admin",
    "operator",
    "moderator",
    "staff",
    "support",
    "system",
    "root",
    "starvector",
    "api",
    "join",
    "me",
    "dev",
    "null",
    "undefined",
  ].map(foldedName),
);

/**
 * A stand-in for the server's table of usual passwords, which is a
 * file the screen does not hold. Three entries are sufficient for the
 * password-usual refusal to be reachable offline.
 */
const MOCK_USUAL = new Set([
  "passwordpassword",
  "123456789012",
  "qwertyuiopasdf",
]);

interface MockAccount {
  /** The NFKC shape, or null for an account with no password. */
  password: string | null;
  /** The compact live recovery code of the player, or null. */
  recovery: string | null;
  /** The notice version the player agreed to, or null (spec R1 §3.2). */
  agreedNotice: number | null;
}

/** The cause that refuses a new password, or null (spec A2 §5.1). */
function passwordRefusal(password: string, username: string): string | null {
  if (!allOk(passwordChecks(password, username))) {
    return "password-rule";
  }
  return MOCK_USUAL.has(password.normalize("NFKC").toLowerCase())
    ? "password-usual"
    : null;
}

/** The mock's photo credit: every revealed photo gets one. */
function creditFor(imageId: string) {
  const title = `Mock photo ${imageId.slice(0, 6)}`;
  return {
    source: "Wikimedia Commons",
    title,
    page: `https://commons.wikimedia.org/wiki/File:${title.replaceAll(" ", "_")}.jpg`,
  };
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
 * Each name is a legal username of spec A2 §4.1, and the label is
 * the username: one name for each player, and no two rows share one.
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
    const name = `${first}-${second}-${index}`;
    rows.push({
      player: name,
      // The username is the one name (spec A2 ruling 3).
      display_name: name,
      avatar_hash: null,
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
    avatar_hash: null,
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
  // The identity moves when a different account signs in.
  let player = options.player ?? "ade";
  let signedIn = options.signedIn ?? true;
  let operatorCode = options.operatorCode ?? null;
  const noticeRequired = options.noticeRequired ?? false;
  const noticeVersion = options.noticeVersion ?? NOTICE_VERSION;

  // Full-mock accounts (spec A2): in memory for the session.
  const accounts = new Map<string, MockAccount>([
    [
      player,
      {
        password: options.hasPassword === false ? null : MOCK_PASSWORD,
        recovery: null,
        agreedNotice: options.noticeAgreed === true ? noticeVersion : null,
      },
    ],
  ]);

  /** True when the signed-in player agreed to the current notice. */
  function agreed(): boolean {
    return accounts.get(player)?.agreedNotice === noticeVersion;
  }
  let recoveryCount = 0;

  function nextRecoveryCode(): string {
    recoveryCount += 1;
    return fromAlphabet(
      `recovery-code:${recoveryCount}`,
      DEVICE_ALPHABET,
      RECOVERY_CODE_LENGTH,
    );
  }

  function refused<T>(status: number, cause: string): Promise<T> {
    return Promise.reject(new ApiError(status, cause));
  }

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
      credit: creditFor(targetId(day)),
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

  // Full-mock account state (spec A1): the description and the
  // avatar digest, kept in memory for the session. The digest
  // derives from the byte count alone, so the adapter stays
  // deterministic with no hashing dependency.
  let description = "";
  let avatarHash: string | null = null;

  // Full-mock sessions (spec BR1 §4): this device plus one phone.
  let sessions: SessionRow[] = [
    {
      id: seededHex("session:this", 64),
      label: "Chrome on Mac",
      created_at: `${shiftDay(today, -12)}T09:14:00+00:00`,
      current: true,
    },
    {
      id: seededHex("session:phone", 64),
      label: "Safari on iPhone",
      created_at: `${shiftDay(today, -3)}T21:40:00+00:00`,
      current: false,
    },
  ];
  let codeCount = 0;

  /** A sign-in on this device: the identity moves to the account. */
  function enter(name: string): void {
    player = name;
    signedIn = true;
    if (!sessions.some((row) => row.current)) {
      sessions = [
        {
          id: seededHex(`session:this:${name}`, 64),
          label: "Chrome on Mac",
          created_at: `${today}T09:14:00+00:00`,
          current: true,
        },
        ...sessions,
      ];
    }
  }

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
        sends: 12 + (submittedToday ? 1 : 0),
        relation_vocabulary: ["left-of", "right-of", "above", "below"],
        canvas_px: 512,
        min_strokes: 2,
        closes_at: null,
      });
    },
    submit(day: string, record: WireRecord): Promise<SubmissionAck> {
      // The agreement comes first, as on the server (spec R1 §3.3).
      if (noticeRequired && !agreed()) {
        return Promise.reject(new ApiError(409, "notice"));
      }
      if (day !== today) {
        return Promise.reject(new ApiError(409, "day-moved"));
      }
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
        day,
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
    startDay(): Promise<{ ok: boolean }> {
      // One constant answer in each condition (spec R1 §4). The mock
      // keeps no start record: it reads no clock.
      return Promise.resolve({ ok: true });
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
        min_strokes: 2,
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
        credit: creditFor(targetId(day)),
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
      // The floor of spec A2 §9.5: the caller's own row travels with
      // the public flag off until the caller has played 3 earlier
      // days. The cast is past the floor.
      const earlier = playedDays.filter((played) => played < day).length;
      const rows: LeaderboardRow[] = [
        {
          player,
          display_name: player,
          avatar_hash: avatarHash,
          p: own.p,
          target_rank: own.target_rank,
          decoy_count: own.decoy_count,
          streak: streak(),
          public: earlier >= MOCK_BOARD_FLOOR_DAYS,
        },
      ];
      for (const name of CAST) {
        const trial = trialFor(`lb:${day}:${name}`);
        rows.push({
          player: name,
          display_name: name,
          avatar_hash: null,
          p: trial.p,
          target_rank: trial.target_rank,
          decoy_count: trial.decoy_count,
          streak: 1 + Math.floor(21 * draw(`lbstreak:${day}:${name}`)),
          public: true,
        });
      }
      rows.sort((a, b) => b.p - a.p);
      return Promise.resolve({
        day,
        rows,
        floor: {
          played_days: MOCK_BOARD_FLOOR_DAYS,
          caller_played_days: earlier,
        },
      });
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
      if (!signedIn) {
        // The server's constant 401: the shell shows the gate screen.
        return Promise.reject(new ApiError(401, undefined, "unauthorized"));
      }
      return Promise.resolve({
        player,
        display_name: player,
        streak: streak(),
        reminder: false,
        description,
        avatar_hash: avatarHash,
        has_password: (accounts.get(player)?.password ?? null) !== null,
        operator_code: operatorCode === null ? null : { ...operatorCode },
        notice: {
          version: noticeVersion,
          agreed: agreed(),
          required: noticeRequired,
        },
      });
    },
    postConsent(notice: number): Promise<ConsentAck> {
      // The player agrees to the text the player read: a number that
      // is not the current one is refused (spec R1 §3.2).
      if (notice !== noticeVersion) {
        return refused(409, "notice-version");
      }
      const account = accounts.get(player) ?? {
        password: null,
        recovery: null,
        agreedNotice: null,
      };
      accounts.set(player, { ...account, agreedNotice: noticeVersion });
      return Promise.resolve({ agreed: true, notice: noticeVersion });
    },
    putAccount(text: string): Promise<{ description: string }> {
      description = text;
      return Promise.resolve({ description });
    },
    putAvatar(image: Blob): Promise<{ avatar_hash: string | null }> {
      avatarHash = seededHex(`avatar:${image.size}`, 64);
      return Promise.resolve({ avatar_hash: avatarHash });
    },
    deleteAvatar(): Promise<{ avatar_hash: string | null }> {
      avatarHash = null;
      return Promise.resolve({ avatar_hash: null });
    },
    avatarUrl(forPlayer: string, hash: string): string {
      // A deterministic placeholder in the manner of imageUrl —
      // the hash label makes a changed picture readable.
      const label = hash.slice(0, 6);
      const initial = forPlayer.slice(0, 2).toUpperCase();
      const svg =
        `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">` +
        `<circle cx="32" cy="32" r="32" fill="#434c5e"/>` +
        `<text x="32" y="30" font-size="16" fill="#eceff4" ` +
        `text-anchor="middle" font-family="monospace">${initial}</text>` +
        `<text x="32" y="48" font-size="9" fill="#97a1b4" ` +
        `text-anchor="middle" font-family="monospace">${label}</text></svg>`;
      return `data:image/svg+xml,${encodeURIComponent(svg)}`;
    },
    getAbout(): Promise<AboutView> {
      return Promise.resolve({
        test_season: true,
        photo_count: DECOY_COUNT + 1,
        closes_at_utc: "22:00",
        public_data_url: options.publicDataUrl ?? null,
      });
    },
    getSessions(): Promise<SessionsView> {
      return Promise.resolve({ sessions: sessions.map((row) => ({ ...row })) });
    },
    removeSession(id: string): Promise<{ removed: number }> {
      const before = sessions.length;
      sessions = sessions.filter((row) => row.id !== id || row.current);
      if (sessions.length === before) {
        return Promise.reject(new ApiError(404, undefined, "no session"));
      }
      return Promise.resolve({ removed: 1 });
    },
    signOutOthers(): Promise<{ removed: number }> {
      const removed = sessions.filter((row) => !row.current).length;
      sessions = sessions.filter((row) => row.current);
      return Promise.resolve({ removed });
    },
    signOut(): Promise<{ signed_out: boolean }> {
      sessions = sessions.filter((row) => !row.current);
      signedIn = false;
      return Promise.resolve({ signed_out: true });
    },
    issueDeviceCode(): Promise<DeviceCodeView> {
      codeCount += 1;
      const code = fromAlphabet(`device-code:${codeCount}`, DEVICE_ALPHABET, 8);
      // The one clock read in the mock: a code's expiry is a live
      // countdown, and a fixed instant reads as expired in each
      // session after it. Nothing byte-compares this field.
      return Promise.resolve({
        code: `${code.slice(0, 4)}-${code.slice(4)}`,
        expires_at: new Date(Date.now() + 10 * 60 * 1000).toISOString(),
      });
    },
    redeemDeviceCode(code: string): Promise<SignInAck> {
      const compact = code.replaceAll(/[\s-]/g, "").toUpperCase();
      if (!/^[ABCDEFGHJKMNPQRSTUVWXYZ2-9]{8}$/.test(compact)) {
        return Promise.reject(new ApiError(400, "bad-code"));
      }
      enter(player);
      return Promise.resolve({ player, display_name: player });
    },
    exportUrl(): string {
      return "data:application/json,%7B%7D";
    },
    getDoor(): Promise<{ open: boolean }> {
      // The full-mock world is a dev world, thus the door is on.
      return Promise.resolve({ open: true });
    },
    postDoor(
      name: string,
      _displayName?: string,
      _operatorToken?: string,
    ): Promise<{ player: string; display_name: string }> {
      // A door record has no password (spec A2 §10.2), and the label
      // on the wire is the name (ruling 3).
      if (!accounts.has(name)) {
        accounts.set(name, {
          password: null,
          recovery: null,
          agreedNotice: null,
        });
      }
      enter(name);
      return Promise.resolve({ player: name, display_name: name });
    },

    // ── spec A2: accounts with a username and a password ───────
    getSignup(): Promise<SignupView> {
      // The full-mock world makes accounts, thus the gate offers it.
      return Promise.resolve({ open: true, notice_version: noticeVersion });
    },
    signUp(
      username: string,
      password: string,
      agreesPublic: boolean,
    ): Promise<RecoveryAck> {
      // No account without the agreement to the notice (spec R1
      // §3.2). Then the server's sequence: the name rules, the
      // password rules, and the claim of the folded shape.
      if (agreesPublic !== true) {
        return refused(400, "notice");
      }
      const name = normalizeUsername(username);
      if (!allOk(usernameChecks(name))) {
        return refused(400, "name-rule");
      }
      if (MOCK_RESERVED.has(foldedName(name))) {
        return refused(400, "name-reserved");
      }
      const cause = passwordRefusal(password, name);
      if (cause !== null) {
        return refused(400, cause);
      }
      const folded = foldedName(name);
      if ([...accounts.keys()].some((held) => foldedName(held) === folded)) {
        return refused(409, "name-taken");
      }
      const code = nextRecoveryCode();
      // The sign-up writes the agreement with the account.
      accounts.set(name, {
        password: password.normalize("NFKC"),
        recovery: code,
        agreedNotice: noticeVersion,
      });
      enter(name);
      return Promise.resolve({
        player: name,
        display_name: name,
        recovery_code: displayRecoveryCode(code),
      });
    },
    signIn(username: string, password: string): Promise<SignInAck> {
      const name = normalizeUsername(username);
      const account = accounts.get(name);
      // One answer for no account, no password, and a bad password.
      if (
        account === undefined ||
        account.password === null ||
        account.password !== password.normalize("NFKC")
      ) {
        return refused(401, "sign-in");
      }
      enter(name);
      return Promise.resolve({ player: name, display_name: name });
    },
    recover(
      username: string,
      recoveryCode: string,
      password: string,
    ): Promise<RecoveryAck> {
      // The password rules read the typed values alone, thus they
      // come first and say nothing about the account. The operator's
      // code is not redeemable here: its hold reads a clock.
      const name = normalizeUsername(username);
      const cause = passwordRefusal(password, name);
      if (cause !== null) {
        return refused(400, cause);
      }
      const account = accounts.get(name);
      if (
        account === undefined ||
        account.recovery === null ||
        account.recovery !== compactRecoveryCode(recoveryCode)
      ) {
        return refused(401, "recovery");
      }
      const code = nextRecoveryCode();
      accounts.set(name, {
        ...account,
        password: password.normalize("NFKC"),
        recovery: code,
      });
      if (name === player) {
        // Each device of the player signs out, then this one signs in.
        sessions = sessions.filter((row) => row.current);
        operatorCode = null;
      }
      enter(name);
      return Promise.resolve({
        player: name,
        display_name: name,
        recovery_code: displayRecoveryCode(code),
      });
    },
    setPassword(
      password: string,
      currentPassword?: string,
    ): Promise<PasswordAck> {
      const account = accounts.get(player) ?? {
        password: null,
        recovery: null,
        agreedNotice: null,
      };
      const cause = passwordRefusal(password, player);
      if (cause !== null) {
        return refused(400, cause);
      }
      const first = account.password === null;
      if (
        !first &&
        account.password !== (currentPassword ?? "").normalize("NFKC")
      ) {
        return refused(403, "password");
      }
      // The first password comes with the first recovery code; a
      // change leaves the recovery code as it is.
      const code = first ? nextRecoveryCode() : null;
      accounts.set(player, {
        ...account,
        password: password.normalize("NFKC"),
        recovery: code ?? account.recovery,
      });
      const signedOut = sessions.filter((row) => !row.current).length;
      sessions = sessions.filter((row) => row.current);
      return Promise.resolve({
        changed: true,
        signed_out: signedOut,
        recovery_code: code === null ? null : displayRecoveryCode(code),
      });
    },
    newRecoveryCode(currentPassword: string): Promise<RecoveryCodeAck> {
      const account = accounts.get(player);
      if (
        account === undefined ||
        account.password === null ||
        account.password !== currentPassword.normalize("NFKC")
      ) {
        return refused(403, "password");
      }
      const code = nextRecoveryCode();
      accounts.set(player, { ...account, recovery: code });
      return Promise.resolve({ recovery_code: displayRecoveryCode(code) });
    },
    stopOperatorCode(): Promise<{ stopped: boolean }> {
      // The same answer with a code and with none.
      operatorCode = null;
      return Promise.resolve({ stopped: true });
    },
  };
}
