/**
 * The live fetch adapter (spec W1 §6 and the §7 surfaces spec S2
 * made live). Relative URLs only — the dev proxy and same-origin
 * serving both work unchanged. No retries and no fallbacks: a
 * failed call throws ApiError and the screen shows it (§8).
 */

import type { Api } from "./client";
import type {
  DayView,
  HistoryView,
  LeaderboardView,
  MeView,
  PracticeDays,
  PracticeScore,
  RefusalBody,
  RevealView,
  SkillBoardView,
  StoredSubmission,
  SubmissionAck,
  WireRecord,
} from "./types";
import { ApiError } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(0);
  }
  if (!response.ok) {
    let body: RefusalBody = {};
    try {
      body = (await response.json()) as RefusalBody;
    } catch {
      // A non-JSON error body keeps the bare status.
    }
    throw new ApiError(response.status, body.cause, body.detail);
  }
  return (await response.json()) as T;
}

function postJson<T>(url: string, payload: unknown): Promise<T> {
  return request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function makeRealApi(): Api {
  return {
    getDay(): Promise<DayView> {
      return request<DayView>("/api/day");
    },
    submit(record: WireRecord): Promise<SubmissionAck> {
      return postJson<SubmissionAck>("/api/submission", record);
    },
    getReveal(day?: string): Promise<RevealView> {
      return request<RevealView>(
        day === undefined
          ? "/api/reveal"
          : `/api/reveal?day=${encodeURIComponent(day)}`,
      );
    },
    imageUrl(imageId: string): string {
      return `/image/${imageId}`;
    },
    getPracticeDays(): Promise<PracticeDays> {
      return request<PracticeDays>("/api/practice");
    },
    scorePractice(day: string, record: WireRecord): Promise<PracticeScore> {
      return postJson<PracticeScore>("/api/practice/score", { day, record });
    },
    getHistory(): Promise<HistoryView> {
      return request<HistoryView>("/api/history");
    },
    getLeaderboard(day?: string): Promise<LeaderboardView> {
      return request<LeaderboardView>(
        day === undefined
          ? "/api/leaderboard"
          : `/api/leaderboard?day=${encodeURIComponent(day)}`,
      );
    },
    getSkillLeaderboard(): Promise<SkillBoardView> {
      // No credentials option: fetch defaults to same-origin, thus
      // the session cookie rides and the client handles no
      // credential (spec M1 §9).
      return request<SkillBoardView>("/api/leaderboard/skill");
    },
    getSubmission(day: string): Promise<StoredSubmission> {
      return request<StoredSubmission>(
        `/api/submission?day=${encodeURIComponent(day)}`,
      );
    },
    getMe(): Promise<MeView> {
      return request<MeView>("/api/me");
    },
  };
}
