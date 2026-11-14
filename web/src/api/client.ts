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
  PasswordAck,
  PracticeDays,
  PracticeScore,
  RecoveryAck,
  RecoveryCodeAck,
  RevealView,
  SessionsView,
  SignInAck,
  SignupView,
  SkillBoardView,
  StoredSubmission,
  SubmissionAck,
  WireRecord,
} from "./types";

export interface DayApi {
  getDay(): Promise<DayView>;
  /** The day it was composed for: a mismatch is a 409 (spec PL1 §2). */
  submit(day: string, record: WireRecord): Promise<SubmissionAck>;
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
  /** The server wants the operator token once a player exists. */
  postDoor(
    player: string,
    displayName?: string,
    operatorToken?: string,
  ): Promise<DoorAck>;
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

/**
 * Accounts with a username and a password (spec A2 §8). A password
 * and a recovery code travel in a POST body alone, never in a URL.
 */
export interface CredentialApi {
  /** 200 when the server makes accounts; the constant 404 when not. */
  getSignup(): Promise<SignupView>;
  signUp(username: string, password: string): Promise<RecoveryAck>;
  signIn(username: string, password: string): Promise<SignInAck>;
  /** Replaces the password and answers with a new recovery code. */
  recover(
    username: string,
    recoveryCode: string,
    password: string,
  ): Promise<RecoveryAck>;
  /**
   * No current password: the first password of a player from before
   * spec A2, and the answer then holds the first recovery code.
   */
  setPassword(password: string, currentPassword?: string): Promise<PasswordAck>;
  newRecoveryCode(currentPassword: string): Promise<RecoveryCodeAck>;
  /** Removes the operator's code; the session alone is sufficient. */
  stopOperatorCode(): Promise<{ stopped: boolean }>;
}

export type Api = DayApi &
  PracticeApi &
  HistoryApi &
  LeaderboardApi &
  ArchiveApi &
  AccountApi &
  DoorApi &
  AboutApi &
  SessionApi &
  CredentialApi;

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
