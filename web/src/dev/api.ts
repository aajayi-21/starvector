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

/** The token is read at call time, so a new one takes effect at once. */
export type TokenSource = () => string;

function authorized(token: string, init?: RequestInit): RequestInit {
  // No header with no token: that world is the one ruling 7 of
  // spec M1 describes, where nothing holds credentials and the
  // operator plane answers as it always did.
  return token === ""
    ? (init ?? {})
    : { ...init, headers: { Authorization: `Bearer ${token}` } };
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

/**
 * The console's client.
 *
 * `token` is read on each call rather than captured, so pasting a
 * token takes effect on the next request with no rewiring.
 *
 * The image URL cannot carry a header: an `<img src>` is a plain
 * browser fetch. Once players are stored, `/image/{id}` falls back
 * to the revealed-target gate for a caller with no bearer, so the
 * ranking thumbnails of a day that is closed but not revealed stop
 * loading. Putting the token in the URL would fix that and is
 * refused: it would land in server logs and browser history.
 */
export function makeDevApi(token: TokenSource = () => ""): DevApi {
  return {
    getDays: () => request<DevDays>("/api/dev/days", authorized(token())),
    getSubmission: (day) =>
      request<DevStored>(
        `/api/dev/submission?day=${encodeURIComponent(day)}`,
        authorized(token()),
      ),
    getRankings: (day) =>
      request<DevRankings>(
        `/api/dev/rankings?day=${encodeURIComponent(day)}`,
        authorized(token()),
      ),
    postOpen: () =>
      request<LifecycleAck>(
        "/api/day/open",
        authorized(token(), { method: "POST" }),
      ),
    postClose: () =>
      request<LifecycleAck>(
        "/api/day/close",
        authorized(token(), { method: "POST" }),
      ),
    postReveal: () =>
      request<LifecycleAck>(
        "/api/day/reveal",
        authorized(token(), { method: "POST" }),
      ),
    imageUrl: (imageId) => `/image/${imageId}`,
  };
}
