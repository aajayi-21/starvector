/**
 * The dev wire shapes, verbatim from service/server.py's dev
 * handlers (spec S2 §5). The console mirrors, never extends.
 */

import type { TrialValue, WireRecord } from "../api/types";

export type DevDayStatus = "open" | "closed" | "revealed";

export interface DevDayRow {
  day: string;
  status: DevDayStatus;
  trial_code: string;
  target_id: string;
  commitment: string;
  submitted: boolean;
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
