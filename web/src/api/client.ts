/**
 * The Api interface the screens consume (spec W1 §6) and the
 * composite wiring: live adapters where the server has the surface,
 * the deterministic mock elsewhere (§7). No screen holds a URL.
 */

import { createContext, useContext } from "react";
import type {
  DayView,
  HistoryView,
  LeaderboardView,
  MeView,
  PracticeDays,
  PracticeScore,
  RevealView,
  StoredSubmission,
  SubmissionAck,
  WireRecord,
} from "./types";

export interface DayApi {
  getDay(): Promise<DayView>;
  submit(record: WireRecord): Promise<SubmissionAck>;
  /** No argument: the latest day (live). With a day: §7 scaffold. */
  getReveal(day?: string): Promise<RevealView>;
  imageUrl(imageId: string): string;
}

export interface PracticeApi {
  getPracticeDays(): Promise<PracticeDays>;
  scorePractice(day: string, record: WireRecord): Promise<PracticeScore>;
}

export interface HistoryApi {
  getHistory(): Promise<HistoryView>;
}

export interface LeaderboardApi {
  getLeaderboard(day: string): Promise<LeaderboardView>;
}

export interface ArchiveApi {
  getSubmission(day: string): Promise<StoredSubmission>;
}

export interface AccountApi {
  getMe(): Promise<MeView>;
}

export type Api = DayApi &
  PracticeApi &
  HistoryApi &
  LeaderboardApi &
  ArchiveApi &
  AccountApi;

export type ApiMode = "composite" | "mock";

/**
 * The composite: every surface is live (spec S2 made the §7
 * contract real). Full-mock mode serves everything from the mock
 * adapter — offline UI work and tests.
 */
export function composeApi(live: Api, mock: Api, mode: ApiMode): Api {
  return mode === "mock" ? mock : live;
}

export const ApiContext = createContext<Api | null>(null);

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (api === null) {
    throw new Error("useApi called without an ApiContext provider");
  }
  return api;
}
