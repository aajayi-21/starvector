/**
 * The live fetch adapter (spec W1 §6). Relative URLs only — the dev
 * proxy and same-origin serving both work unchanged. No retries and
 * no fallbacks: a failed call throws ApiError and the screen shows
 * it (§8, fail loudly).
 */

import type { DayApi, PracticeApi } from "./client";
import type {
  DayView,
  PracticeDays,
  PracticeScore,
  RefusalBody,
  RevealView,
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

export function makeRealApi(): DayApi & PracticeApi {
  return {
    getDay(): Promise<DayView> {
      return request<DayView>("/api/day");
    },
    submit(record: WireRecord): Promise<SubmissionAck> {
      return postJson<SubmissionAck>("/api/submission", record);
    },
    getReveal(day?: string): Promise<RevealView> {
      if (day !== undefined) {
        // §7 scaffold: the live server serves the latest day alone.
        // The composite client routes day-addressed reveals to the
        // mock adapter; reaching this line is a wiring bug.
        throw new ApiError(501, undefined, "per-day reveal is not live yet");
      }
      return request<RevealView>("/api/reveal");
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
  };
}
