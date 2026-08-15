/**
 * Typed fetch over the dev endpoints and the day lifecycle. Errors
 * carry the page rule: detail, else cause, else "refused"; a thrown
 * fetch reads as the server not answering.
 */

import type { DevDays, DevRankings, DevStored, LifecycleAck } from "./types";

export class DevApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "DevApiError";
    this.status = status;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new DevApiError(0, "the server did not answer");
  }
  if (!response.ok) {
    let message = "refused";
    try {
      const body = (await response.json()) as {
        detail?: string;
        cause?: string;
      };
      message = body.detail ?? body.cause ?? "refused";
    } catch {
      // A non-JSON error body keeps the generic message.
    }
    throw new DevApiError(response.status, message);
  }
  return (await response.json()) as T;
}

export interface DevApi {
  getDays(): Promise<DevDays>;
  getSubmission(day: string): Promise<DevStored>;
  getRankings(day: string): Promise<DevRankings>;
  postOpen(): Promise<LifecycleAck>;
  postClose(): Promise<LifecycleAck>;
  postReveal(): Promise<LifecycleAck>;
  imageUrl(imageId: string): string;
}

export function makeDevApi(): DevApi {
  return {
    getDays: () => request<DevDays>("/api/dev/days"),
    getSubmission: (day) =>
      request<DevStored>(`/api/dev/submission?day=${encodeURIComponent(day)}`),
    getRankings: (day) =>
      request<DevRankings>(`/api/dev/rankings?day=${encodeURIComponent(day)}`),
    postOpen: () => request<LifecycleAck>("/api/day/open", { method: "POST" }),
    postClose: () =>
      request<LifecycleAck>("/api/day/close", { method: "POST" }),
    postReveal: () =>
      request<LifecycleAck>("/api/day/reveal", { method: "POST" }),
    imageUrl: (imageId) => `/image/${imageId}`,
  };
}
