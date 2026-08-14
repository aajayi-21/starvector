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
  /** §7 contract field — absent from the live server today. */
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

// ── §7: the backend-phase contract, mock-served this phase ──────

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
  player: string;
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
  streak: number;
  reminder: boolean;
  public: boolean;
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
