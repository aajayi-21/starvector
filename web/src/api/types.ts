/**
 * Wire types for the trial server (spec W1 §6) and the backend-phase
 * contract (§7). The system of record for the live shapes is
 * service/server.py and core/intake.py — these types mirror, never
 * extend, what the server accepts and returns.
 */

// ── §6: live today ──────────────────────────────────────────────

/**
 * "closing" sits between open and closed (spec BR1 §3): the close
 * stops new sends before it scores. A screen treats it like closed.
 */
export type DayStatus = "open" | "closing" | "closed" | "revealed";

export interface DayView {
  day: string;
  trial_code: string;
  status: DayStatus;
  commitment: string;
  player: string;
  submitted: boolean;
  relation_vocabulary: string[];
  canvas_px: number;
  /** The Layer 0 stroke floor: a sketch with fewer does not send. */
  min_strokes: number;
  /** Revealed days only. */
  target_id?: string;
  secret?: string;
  /** Served by the day view; null when no close time is set. */
  closes_at?: string | null;
}

export type WirePoint = [number, number];

export interface WireStroke {
  points: WirePoint[];
  /** Always present, null for an ungrouped stroke. */
  group_id: string | null;
  /** Present only when the stroke has a palette color; ink omits it. */
  color?: string;
}

export interface WireGroup {
  id: string;
  label: string;
}

export interface WireRelation {
  relation: string;
  of: [string, string];
}

/** The frozen L0 record shape — all five keys, always. */
export interface WireRecord {
  impressions: string[];
  canvas_strokes: WireStroke[];
  groups: WireGroup[];
  relations: WireRelation[];
  pasted_text: string | null;
}

export interface SubmissionAck {
  trial_id: string;
  /** The day the send landed on (spec PL1 §2). */
  day: string;
  atom_count: number;
}

export interface TrialValue {
  p: number;
  decoy_count: number;
  beaten: number;
  tied: number;
  target_rank: number;
}

export interface ReportRow {
  atom_id: string;
  atom_text: string;
  element: string | null;
  weight: number;
  similarity: number;
  rarity: number;
}

/** Where a revealed photo comes from (spec BR1 §6). */
export interface ImageCredit {
  source: string;
  title: string;
  /** The file page, which names the author and the license. */
  page: string;
}

export interface RevealView {
  day: string;
  /** Null when the server holds no release manifest. */
  credit: ImageCredit | null;
  target_id: string;
  secret: string;
  commitment: string;
  check: string;
  trial: TrialValue | null;
  report: ReportRow[];
}

export interface PracticeDayRow {
  day: string;
  target_id: string;
  trial_code: string;
}

export interface PracticeDays {
  days: PracticeDayRow[];
  min_strokes: number;
}

export interface RankingHeadRow {
  position: number;
  fused: number;
  is_target: boolean;
}

export interface PracticeScore {
  day: string;
  target_id: string;
  credit: ImageCredit | null;
  trial: TrialValue;
  target_position: number;
  ranking_head: RankingHeadRow[];
  report: ReportRow[];
}

// ── §7: the contract spec S2 made live ─────────────────────────

export interface HistoryDayRow {
  day: string;
  trial_code: string;
  p: number;
  target_rank: number;
  decoy_count: number;
}

export interface SkillValue {
  theta: number;
  shrunk: number;
  evidence_p: number;
  n: number;
}

export interface HistoryView {
  days: HistoryDayRow[];
  skill: SkillValue | null;
}

export interface LeaderboardRow {
  /**
   * The username (spec A2 ruling 3): the store key, the React key,
   * the identity compare, and the one name a board shows.
   */
  player: string;
  /** Equal to `player` since spec A2. The boards read `player`. */
  display_name: string;
  /** Joined at read time (spec A1, D5). Null: no picture. */
  avatar_hash: string | null;
  p: number;
  target_rank: number;
  decoy_count: number;
  streak: number;
  /**
   * False on the caller's own row while the caller is below the
   * floor of the daily board (spec A2 §9.5): no other player gets
   * that row. The server filters; the screen only marks the row.
   */
  public: boolean;
}

/** The floor of the daily board (spec A2 §9.5), from the wire. */
export interface BoardFloor {
  /** Earlier played days a row needs before it is public. */
  played_days: number;
  /** Earlier played days the caller has. */
  caller_played_days: number;
}

export interface LeaderboardView {
  day: string;
  rows: LeaderboardRow[];
  floor: BoardFloor;
}

export interface StoredSubmission {
  trial_id: string;
  record: WireRecord;
}

/** The two times of a live operator's code (spec A2 §6.1). */
export interface OperatorCodeView {
  issued_at: string;
  /** The code works from this instant: 24 hours after it was made. */
  usable_at: string;
}

export interface MeView {
  /** The username: the one name of a player (spec A2 ruling 3). */
  player: string;
  /** Equal to `player` since spec A2. */
  display_name: string;
  streak: number;
  reminder: boolean;
  /** The account description; empty when nothing is written. */
  description: string;
  /** The stored avatar's digest, or null - the cache-busting key. */
  avatar_hash: string | null;
  /** False for a player from before spec A2 with no password set. */
  has_password: boolean;
  /** Null, or the times of the operator's live recovery code. */
  operator_code: OperatorCodeView | null;
  /** The notice that results are public (spec R1 §3). */
  notice: NoticeView;
}

/**
 * Where a player stands with the notice that results are public
 * (spec R1 §3). The screen compares `version` with the number it was
 * built with before it shows the text.
 */
export interface NoticeView {
  /** The server's current notice version. */
  version: number;
  /** True when this player has agreed to that version. */
  agreed: boolean;
  /** True when this server publishes results: a send then needs it. */
  required: boolean;
}

/** The answer of POST /api/account/consent (spec R1 §3.2). */
export interface ConsentAck {
  agreed: boolean;
  /** The notice version the agreement is to. */
  notice: number;
}

// ── spec BR1: the season facts, sessions, and device codes ─────

/** GET /api/about — no session needed (spec BR1 §6). */
export interface AboutView {
  /** A development pool: the numbers are test numbers (R13). */
  test_season: boolean;
  photo_count: number;
  /** The daily rollover hour, "HH:MM" UTC, or null when unset. */
  closes_at_utc: string | null;
  /**
   * Where the published snapshots of the public database can be
   * downloaded (spec R1 §3.1), or null when none is published yet.
   */
  public_data_url: string | null;
}

export interface SessionRow {
  /** A one-way digest: the handle for signing that device out. */
  id: string;
  label: string;
  created_at: string;
  current: boolean;
}

export interface SessionsView {
  sessions: SessionRow[];
}

export interface DeviceCodeView {
  /** "ABCD-EFGH". */
  code: string;
  expires_at: string;
}

export interface SignInAck {
  player: string;
  display_name: string;
}

// ── spec A2: sign-up, sign-in, and recovery ─────────────────────

/** GET /api/signup answers this when sign-up is open; 404 when not. */
export interface SignupView {
  open: boolean;
  /** The server's notice version (spec R1 §3.2). */
  notice_version: number;
}

/**
 * The answer of a sign-up and of a recovery: the session cookie came
 * with it, and the recovery code is in this answer one time.
 */
export interface RecoveryAck {
  player: string;
  display_name: string;
  /** Six groups of four: "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2". */
  recovery_code: string;
}

export interface PasswordAck {
  changed: boolean;
  /** How many other devices the change signed out. */
  signed_out: number;
  /** A code only when this was the account's first password. */
  recovery_code: string | null;
}

export interface RecoveryCodeAck {
  recovery_code: string;
}

// ── spec A1: the account writers and the open door ──────────────

export interface AccountAck {
  description: string;
}

export interface AvatarAck {
  avatar_hash: string | null;
}

/** GET /api/door answers this when the door is on; 404 when off. */
export interface DoorView {
  open: boolean;
}

export interface DoorAck {
  player: string;
  display_name: string;
}

// ── spec M1 §8: players and the skill board ─────────────────────

/** A closed interval [low, high] in the units of its field. */
export type Interval = [number, number];

/**
 * One row of the skill board.
 *
 * Ruling 17 of 2026-08-16: every player holds a row and the
 * eligible ones hold a rank. A player below the trial floor keeps
 * `theta`, `y`, `v` and the evidence values, which read their own
 * pair alone, and their ranking fields are null — the fit and the
 * rank simulation read the eligible set, so ranking one of them
 * would move everybody else's rank. The chart plots every row and
 * the ranked table reads the eligible ones.
 */
export interface SkillBoardRow {
  player: string;
  display_name: string;
  /** Joined at read time (spec A1, D5). Null: no picture. */
  avatar_hash: string | null;
  n: number;
  /** The server owns the floor compare, so the screen never redoes it. */
  eligible: boolean;
  /** The skill number. Rises with skill (spec M1 §10). */
  theta: number;
  /** The shrunk estimate, on the log theta scale. Null below the floor. */
  shrunk: number | null;
  /** The accurate estimate of log theta. What the chart plots. */
  y: number;
  v: number;
  /** Fractional - a posterior expectation, not a position. */
  expected_rank: number | null;
  rank_low: number | null;
  rank_high: number | null;
  evidence_p: number;
  log_e_value: number;
  /**
   * 1/E, and SMALL is the evidence direction. The mixture is cut
   * at a skill number of one (the 2026-08-16 amendment), thus this
   * asks "is this player above the baseline" and a weak run does
   * not read as strong evidence.
   */
  anytime_significance: number;
}

/** The no-skill range at a trial count, on the log theta scale. */
export interface BaselineBandPoint {
  n: number;
  low: number;
  high: number;
}

export interface PopulationFit {
  mu: number;
  /** A fitted tau of 0.0 is a correct answer and is published. */
  tau: number;
  mu_spread: number;
  fitted: boolean;
  halvings: number;
}

export interface VariationReport {
  q_statistic: number;
  dof: number;
  q_significance: number;
  tau_low: number;
  tau_high: number | null;
  /** exp(tau): the multiplicative width a player can read. */
  tau_multiplicative: number;
  prediction_low: number;
  prediction_high: number;
}

/** The site-wide claim as a natural frequency (spec M1 §6). */
export interface DiscoveryReport {
  level: number;
  tested: number;
  flagged: number;
  expected_by_luck: number;
}

export interface SkillBoardView {
  /**
   * Computed, not a switch: one eligible player turns the board on
   * and a new deployment gates itself. Distinct from `provisional`,
   * which is the population's own state.
   */
  active: boolean;
  player_count: number;
  eligible_count: number;
  degenerate_count: number;
  /** Trials, per player. Membership stays here (2026-08-16). */
  eligibility_floor: number;
  /** The recomputed value, published as a report alone, or null. */
  recomputed_floor: number | null;
  /** Eligible players, before the fit runs. A different quantity. */
  fit_floor: number;
  provisional: boolean;
  rows: SkillBoardRow[];
  baseline_band: BaselineBandPoint[];
  population: PopulationFit | null;
  variation: VariationReport | null;
  discovery: DiscoveryReport | null;
  day?: string;
  created_at?: string | null;
  rank_sample_count?: number;
}

// ── Refusals ────────────────────────────────────────────────────

/** Server refusal bodies: {cause, detail} 400s, {cause} 409s, constant {detail} 404s. */
export interface RefusalBody {
  cause?: string;
  detail?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly refusalCause: string | undefined;
  readonly detail: string | undefined;

  constructor(status: number, refusalCause?: string, detail?: string) {
    super(detail ?? refusalCause ?? `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.refusalCause = refusalCause;
    this.detail = detail;
  }
}

const CAUSE_COPY: Record<string, string> = {
  "already-submitted": "You've already sent today's session.",
  "day-closed": "Today's session has closed. Your results come soon.",
  "day-moved":
    "That day has closed, so this wasn't sent. Your sketch is still here.",
  "day-required":
    "This page is out of date. Reload it — your sketch is saved on this device.",
  "too-much-drawing":
    "That's more drawing than one send can hold. Clear some strokes and try again.",
  "body-too-large":
    "That's more than one send can hold. Clear some strokes and try again.",
  "practice-limit":
    "That's a lot of practice for one hour. Take a break and try again later.",
  "bad-shape": "Something went wrong sending your sketch. Try again.",
  "bad-code":
    "That code didn't work. A code works once and expires after 10 minutes.",
  "too-many-attempts": "Too many tries. Wait a few minutes, then try again.",
  // Spec A2 §8: the refusals of sign-up, sign-in, and recovery. The
  // sign-in line does not say which of the two was wrong, because the
  // server gives one answer for each wrong pair.
  "name-rule":
    "That username doesn't fit the rules. Use 3 to 20 characters: letters a to z, digits, and hyphens, starting with a letter.",
  "name-reserved": "That username is reserved. Choose a different one.",
  "name-taken":
    "That username is taken, or it looks too much like one that is. Choose a different one.",
  "password-rule":
    "That password doesn't fit the rules. Use 12 to 128 characters, without your username in it.",
  "password-usual":
    "That password is one many people use, so it is easy to guess. Choose a different one.",
  "sign-in": "The username or the password is wrong.",
  recovery:
    "That didn't work. Check the username and the recovery code. A recovery code works one time, and a code from the operator works 24 hours after it was made.",
  password: "That isn't your current password.",
  origin:
    "This page couldn't prove where the request came from. Reload the page and try again.",
  "no-accounts": "This server has no accounts, so there's nothing to add.",
  // Spec R1 §3: the two refusals of the notice that results are
  // public. The drawing screen has its own line for a refused send,
  // which says that the sketch stays.
  notice:
    "This needs your agreement that your results are public. Reload the page and try again.",
  "notice-version":
    "This page is out of date, so it shows an earlier notice. Reload it and try again.",
  "no-scoreable-atom":
    "Add at least one word or a few strokes before you send.",
  // The Layer 0 gates (core/types.py INTAKE_CAUSES), in plain words.
  "min-ink": "Your sketch is too small to read. Draw a little more.",
  "min-strokes":
    "A sketch needs at least two strokes. Add another, or clear it and send words only.",
  "text-length": "One of your words or your notes is too long. Shorten it.",
  "atom-count":
    "That's more than one send can hold. Remove a few words or labels.",
};

/** True for the server's deliberate constant refusals (404s). */
export function isRefusal(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/**
 * True for the server's constant 401 - no session on this device.
 *
 * 401 exactly. A network failure is ApiError(0) and a 500 is a
 * 500, and neither means "you are signed out". Showing a player
 * the sign-in form while the server is down sends them somewhere
 * no password helps.
 */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/**
 * Player-facing copy for a failed credential call (spec A2 §8). The
 * constant 404 on those paths means the server has no password
 * sign-in at all — a server with one fixed player, or one with no
 * pepper — and that is not "something went wrong".
 */
export function credentialMessage(error: unknown): string {
  return isRefusal(error)
    ? "This server doesn't use usernames and passwords."
    : friendlyMessage(error);
}

/**
 * Player-facing copy for a failed call. Known causes — the intake
 * gates among them — map to plain sentences; another refusal shows
 * its detail; a network failure reads as no connection. The raw
 * cause token is never shown.
 */
export function friendlyMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.refusalCause !== undefined) {
      const mapped = CAUSE_COPY[error.refusalCause];
      if (mapped !== undefined) {
        return mapped;
      }
      return error.detail ?? "Something went wrong. Try again.";
    }
    if (error.status === 0) {
      return "Can't reach Starvector. Check your connection and try again.";
    }
    return error.detail ?? "Something went wrong. Try again.";
  }
  return "Can't reach Starvector. Check your connection and try again.";
}
