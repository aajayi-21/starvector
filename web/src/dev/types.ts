/**
 * The dev wire shapes, verbatim from service/server.py's dev
 * handlers (spec S2 §5). The console mirrors, never extends.
 */

import type { ImageCredit, TrialValue, WireRecord } from "../api/types";

/** "closing": the close stopped the sends and is scoring (spec BR1 §3). */
export type DevDayStatus = "open" | "closing" | "closed" | "revealed";

export interface DevDayRow {
  day: string;
  status: DevDayStatus;
  trial_code: string;
  target_id: string;
  commitment: string;
  /** The configured player sent this day. */
  submitted: boolean;
  /** Each player's sends this day (spec BR1 §7). */
  sends: number;
}

export interface DevDays {
  days: DevDayRow[];
}

export interface DevStored {
  day: string;
  player: string;
  trial_id: string;
  received_at: string;
  record: WireRecord;
}

export interface DevRankRow {
  position: number;
  image_id: string;
  fused: number;
  channels: Record<string, number>;
  is_target: boolean;
}

export interface DevReportRow {
  atom_id: string;
  atom_text: string;
  element: string | null;
  weight: number;
  similarity: number;
  rarity: number;
}

export interface DevRankings {
  trial: TrialValue;
  target_position: number;
  channel_names: string[];
  rankings: DevRankRow[];
  report: DevReportRow[];
}

export interface LifecycleAck {
  [key: string]: unknown;
}

// ── spec A1 §5: the roster and the player history ───────────────

/**
 * "configured" is the ruling-7 world: no record is stored and the
 * configured player is the identity, so the roster holds one
 * synthetic row for it rather than an empty table.
 */
export type DevPlayerStatus = "active" | "revoked" | "configured";

export interface DevRosterRow {
  player: string;
  display_name: string;
  status: DevPlayerStatus;
  /** Null on the synthetic configured row alone. */
  created_at: string | null;
  /** Live sessions: devices signed in now (spec BR1 §7.4). */
  devices: number;
  /** The start of the newest live session. */
  last_signed_in: string | null;
  /** Device codes that wait to be typed. */
  device_codes: number;
  sends: number;
}

export interface DevRoster {
  players: DevRosterRow[];
}

export interface DevHistoryTrial {
  p: number;
  target_rank: number;
  decoy_count: number;
  beaten: number;
  tied: number;
}

export interface DevHistoryDay {
  day: string;
  status: DevDayStatus;
  trial_code: string;
  target_id: string;
  submitted: boolean;
  /** Null before the day closes, or when nothing was sent. */
  trial: DevHistoryTrial | null;
}

export interface DevHistory {
  player: string;
  days: DevHistoryDay[];
}

/**
 * One minted invite (spec M1 §8).
 *
 * `join_path` is a path and not a full address: the server does
 * not know its public origin and must not trust the Host header
 * for one. The caller puts the origin in front.
 *
 * The token is in this answer and nowhere else — the store keeps
 * its digest alone, so no later read can recover it.
 */
export interface MintedInvite {
  player: string;
  display_name: string;
  token: string;
  join_path: string;
}

// ── spec BR1 §7: the console's growth ───────────────────────────

export interface DevSend {
  player: string;
  display_name: string;
  received_at: string;
  trial_id: string;
  /** Null until the close writes the trial row. */
  trial: DevHistoryTrial | null;
}

export interface DevDayDetail {
  day: string;
  status: DevDayStatus;
  trial_code: string;
  target_id: string;
  commitment: string;
  opened_at: string;
  closed_at: string | null;
  revealed_at: string | null;
  /** Null when the server has no rollover hour. */
  closes_at: string | null;
  scoring_config_hash: string;
  preparation_version_id: string;
  credit: ImageCredit | null;
  /** In the sequence they arrived. */
  sends: DevSend[];
}

export type DevRolloverStep = "open" | "close" | "reveal";
export type DevRunSource = "timer" | "command-line" | "console";
export type DevRunOutcome = "moved" | "nothing due" | "paused" | "failed";

export interface DevPlan {
  at: string;
  /** Empty: nothing is due at that instant. */
  steps: DevRolloverStep[];
  /** The label an open in these steps gets. */
  opens: string | null;
}

export interface DevRun {
  started_at: string;
  finished_at: string;
  source: DevRunSource;
  outcome: DevRunOutcome;
  steps: DevRolloverStep[];
  /** Each line the rollover printed, joined by newlines. */
  detail: string;
}

export interface DevSchedule {
  /** "HH:MM" — null when automatic days are off on this server. */
  closes_at_utc: string | null;
  now: string;
  running_label: string;
  latest: {
    day: string;
    status: DevDayStatus;
    closes_at: string | null;
  } | null;
  paused: boolean;
  pause_changed_at: string | null;
  pause_note: string;
  lock_held: boolean;
  /** Null with no rollover hour. */
  due_now: DevPlan | null;
  next_run: DevPlan | null;
  runs: DevRun[];
}

export interface DevRolloverResult {
  run: DevRun;
  schedule: DevSchedule;
}

export interface DevSession {
  /** The digest of the session secret — no cookie comes from it. */
  id: string;
  label: string;
  created_at: string;
  ends_at: string;
}

export interface DevPlayerDetail {
  player: string;
  display_name: string;
  status: "active" | "revoked";
  created_at: string;
  description: string;
  has_avatar: boolean;
  account_updated_at: string | null;
  sessions: DevSession[];
  device_codes: Array<{ created_at: string; expires_at: string }>;
  sends: number;
}

export interface DevDeviceCode {
  player: string;
  code: string;
  /** "ABCD-EFGH" — the shape a player types. */
  display: string;
  expires_at: string;
}

export interface DevIndexTable {
  name: string;
  rows: number;
  columns: string[];
  view: boolean;
}

export interface DevIndexStatus {
  path: string;
  exists: boolean;
  schema_version: number;
  built_at: string | null;
  /** The store has not changed since the build. */
  current: boolean;
  /** SQLite could not read the file. */
  problem: string | null;
  tables: DevIndexTable[];
}

export interface DevIndexCheck {
  agrees: boolean;
  problems: string[];
}

export type DevCell = string | number | null;

export interface DevQueryResult {
  columns: string[];
  rows: DevCell[][];
  /** More rows agree with the query than the answer holds. */
  truncated: boolean;
  elapsed_ms: number;
}
