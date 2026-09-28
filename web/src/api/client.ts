/**
 * The Api interface the screens consume (spec W1 §6) and the
 * composite wiring. Spec S2 made the §7 contract live, thus the
 * composite serves the live adapter outright and the mock stays
 * for the full-mock mode. No screen holds a URL.
 */

import { createContext, useContext } from "react";
import type {
  AboutView,
  AccountAck,
  AvatarAck,
  DayView,
  DeviceCodeView,
  DoorAck,
  DoorView,
  HistoryView,
  LeaderboardView,
  MeView,
  PracticeDays,
  PracticeScore,
  RevealView,
  SessionsView,
  SignInAck,
  SkillBoardView,
  StoredSubmission,
  SubmissionAck,
  WireRecord,
} from "./types";

export interface DayApi {
  getDay(): Promise<DayView>;
  submit(record: WireRecord): Promise<SubmissionAck>;
  /** No argument: the latest day. With a day: that day's reveal. */
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
  /** No argument: the newest revealed day (spec M1 §8). */
  getLeaderboard(day?: string): Promise<LeaderboardView>;
  getSkillLeaderboard(): Promise<SkillBoardView>;
}

export interface ArchiveApi {
  getSubmission(day: string): Promise<StoredSubmission>;
}

export interface AccountApi {
  getMe(): Promise<MeView>;
  putAccount(description: string): Promise<AccountAck>;
  /** The body is the raw image bytes - downscaled client-side. */
  putAvatar(image: Blob): Promise<AvatarAck>;
  deleteAvatar(): Promise<AvatarAck>;
  /** The hash rides the URL as the cache-busting key. */
  avatarUrl(player: string, avatarHash: string): string;
}

/** The open door (spec A1 §4): dev servers only, 404 elsewhere. */
export interface DoorApi {
  getDoor(): Promise<DoorView>;
  postDoor(player: string, displayName?: string): Promise<DoorAck>;
}

/** The season facts (spec BR1 §6): no session needed. */
export interface AboutApi {
  getAbout(): Promise<AboutView>;
}

/** Sessions, device codes, sign-out, and the data export (BR1 §4–5). */
export interface SessionApi {
  getSessions(): Promise<SessionsView>;
  removeSession(id: string): Promise<{ removed: number }>;
  signOutOthers(): Promise<{ removed: number }>;
  signOut(): Promise<{ signed_out: boolean }>;
  issueDeviceCode(): Promise<DeviceCodeView>;
  redeemDeviceCode(code: string): Promise<SignInAck>;
  /** A same-origin URL the browser downloads as a file. */
  exportUrl(): string;
}

export type Api = DayApi &
  PracticeApi &
  HistoryApi &
  LeaderboardApi &
  ArchiveApi &
  AccountApi &
  DoorApi &
  AboutApi &
  SessionApi;

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
