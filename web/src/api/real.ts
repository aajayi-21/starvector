/**
 * The live fetch adapter (spec W1 §6 and the §7 surfaces spec S2
 * made live). Relative URLs only — the dev proxy and same-origin
 * serving both work unchanged. No retries and no fallbacks: a
 * failed call throws ApiError and the screen shows it (§8).
 */

import type { Api } from "./client";
import type {
  AccountAck,
  AvatarAck,
  DayView,
  DoorAck,
  DoorView,
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
    putAccount(description: string): Promise<AccountAck> {
      return request<AccountAck>("/api/account", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description }),
      });
    },
    putAvatar(image: Blob): Promise<AvatarAck> {
      // Raw bytes, no form encoding — the server reads the magic
      // bytes and ignores any declared type.
      return request<AvatarAck>("/api/account/avatar", {
        method: "PUT",
        body: image,
      });
    },
    deleteAvatar(): Promise<AvatarAck> {
      return request<AvatarAck>("/api/account/avatar", {
        method: "DELETE",
      });
    },
    avatarUrl(player: string, avatarHash: string): string {
      // The hash is the cache-busting key: a new picture changes
      // the URL and no stale copy survives an edit.
      return `/api/avatar/${encodeURIComponent(player)}?v=${avatarHash.slice(0, 8)}`;
    },
    getDoor(): Promise<DoorView> {
      return request<DoorView>("/api/door");
    },
    postDoor(player: string, displayName?: string): Promise<DoorAck> {
      return postJson<DoorAck>("/api/door", {
        player,
        ...(displayName === undefined ? {} : { display_name: displayName }),
      });
    },
  };
}
