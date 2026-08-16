/**
 * Wire types for the trial server (spec W1 §6) and the backend-phase
 * contract (§7). The system of record for the live shapes is
 * service/server.py and core/intake.py — these types mirror, never
 * extend, what the server accepts and returns.
 */

// ── §6: live today ──────────────────────────────────────────────

export type DayStatus = "open" | "closed" | "revealed";

export interface DayView {
  day: string;
  trial_code: string;
  status: DayStatus;
  commitment: string;
  player: string;
  submitted: boolean;
  relation_vocabulary: string[];
  canvas_px: number;
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

export interface RevealView {
  day: string;
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
}

export interface RankingHeadRow {
  position: number;
  fused: number;
  is_target: boolean;
}

export interface PracticeScore {
  day: string;
  target_id: string;
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
  /** The store key: unique, the React key, the identity compare. */
  player: string;
  /** The board label. NOT unique - two players may share one. */
  display_name: string;
  p: number;
  target_rank: number;
  decoy_count: number;
  streak: number;
}

export interface LeaderboardView {
  day: string;
  rows: LeaderboardRow[];
}

export interface StoredSubmission {
  trial_id: string;
  record: WireRecord;
}

export interface MeView {
  player: string;
  display_name: string;
  streak: number;
  reminder: boolean;
}

// ── spec M1 §8: players and the skill board ─────────────────────

/** A closed interval [low, high] in the units of its field. */
export type Interval = [number, number];

/** One row of the skill board. */
export interface SkillBoardRow {
  player: string;
  display_name: string;
  n: number;
  /** The skill number. Rises with skill (spec M1 §10). */
  theta: number;
  /** The shrunk estimate, on the log theta scale. */
  shrunk: number;
  y: number;
  v: number;
  /** Fractional - a posterior expectation, not a position. */
  expected_rank: number;
  rank_low: number;
  rank_high: number;
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
  "already-submitted": "Already sent — one send per day.",
  "day-closed": "The day has closed. Scores arrive at the reveal.",
  "bad-shape": "The sketch could not be encoded. Try again.",
};

/** True for the server's deliberate constant refusals (404s). */
export function isRefusal(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

/**
 * True for the server's constant 401 - no invite on this device.
 *
 * 401 exactly. A network failure is ApiError(0) and a 500 is a
 * 500, and neither means "your invite is not valid here". Telling
 * a player to hunt for a working link while the server is down
 * sends them somewhere no link helps.
 */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/**
 * Player-facing copy for a failed call. Known causes map to full
 * sentences; a refusal with its own player-facing detail (the
 * intake gates write these) shows that detail; a network failure
 * reads as the server not answering. The raw cause token is never
 * shown.
 */
export function friendlyMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.refusalCause !== undefined) {
      const mapped = CAUSE_COPY[error.refusalCause];
      if (mapped !== undefined) {
        return mapped;
      }
      return error.detail ?? "The server refused the request.";
    }
    if (error.status === 0) {
      return "The server did not answer.";
    }
    return error.detail ?? "The server refused the request.";
  }
  return "The server did not answer.";
}
