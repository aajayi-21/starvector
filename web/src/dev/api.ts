/**
 * Typed fetch over the dev endpoints and the day lifecycle. Errors
 * carry the page rule: detail, else cause, else "refused"; a thrown
 * fetch reads as the server not answering.
 */

import type { AboutView } from "../api/types";
import type {
  DevDayDetail,
  DevDays,
  DevDeviceCode,
  DevHistory,
  DevIndexCheck,
  DevIndexStatus,
  DevPlayerDetail,
  DevQueryResult,
  DevRankings,
  DevRolloverResult,
  DevRoster,
  DevSchedule,
  DevStored,
  LifecycleAck,
  MintedInvite,
} from "./types";

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
  //
  // The caller's own headers are merged and not replaced - the
  // mint sends a content type, and a bearer that overwrote it
  // would be a silent loss.
  if (token === "") {
    return init ?? {};
  }
  return {
    ...init,
    headers: {
      ...(init?.headers as Record<string, string> | undefined),
      Authorization: `Bearer ${token}`,
    },
  };
}

async function send(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new DevApiError(0, "the server did not answer");
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await send(url, init);
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
  /** No player names the configured one — today's behavior. */
  getSubmission(day: string, player?: string): Promise<DevStored>;
  getRankings(day: string, player?: string): Promise<DevRankings>;
  getPlayers(): Promise<DevRoster>;
  getHistory(player: string): Promise<DevHistory>;
  postOpen(): Promise<LifecycleAck>;
  postClose(): Promise<LifecycleAck>;
  postReveal(): Promise<LifecycleAck>;
  mintPlayer(player: string, displayName: string): Promise<MintedInvite>;
  imageUrl(imageId: string): string;

  // ── spec BR1 §7 ──
  /** The season facts; a public read with no session. */
  getAbout(): Promise<AboutView>;
  getDay(day: string): Promise<DevDayDetail>;
  getSchedule(): Promise<DevSchedule>;
  setPause(paused: boolean, note: string): Promise<DevSchedule>;
  runRollover(): Promise<DevRolloverResult>;
  getPlayer(player: string): Promise<DevPlayerDetail>;
  /** Null when the player has no picture. */
  getAvatar(player: string): Promise<Blob | null>;
  rotatePlayer(player: string): Promise<MintedInvite>;
  restorePlayer(player: string): Promise<MintedInvite>;
  revokePlayer(player: string): Promise<{ player: string; status: string }>;
  signOutPlayer(player: string): Promise<{ player: string; ended: number }>;
  endSession(
    player: string,
    sessionId: string,
  ): Promise<{ player: string; ended: number }>;
  issueDeviceCode(player: string): Promise<DevDeviceCode>;
  prune(): Promise<{ sessions: number; device_codes: number }>;
  getIndex(): Promise<DevIndexStatus>;
  buildIndex(): Promise<DevIndexStatus>;
  verifyIndex(): Promise<DevIndexCheck>;
  queryIndex(sql: string): Promise<DevQueryResult>;
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
    getSubmission: (day, player) =>
      request<DevStored>(
        `/api/dev/submission?day=${encodeURIComponent(day)}${
          player === undefined ? "" : `&player=${encodeURIComponent(player)}`
        }`,
        authorized(token()),
      ),
    getRankings: (day, player) =>
      request<DevRankings>(
        `/api/dev/rankings?day=${encodeURIComponent(day)}${
          player === undefined ? "" : `&player=${encodeURIComponent(player)}`
        }`,
        authorized(token()),
      ),
    getPlayers: () =>
      request<DevRoster>("/api/dev/players", authorized(token())),
    getHistory: (player) =>
      request<DevHistory>(
        `/api/dev/history?player=${encodeURIComponent(player)}`,
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
    mintPlayer: (player, displayName) =>
      request<MintedInvite>(
        "/api/players",
        authorized(token(), {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            player,
            display_name: displayName,
          }),
        }),
      ),
    imageUrl: (imageId) => `/image/${imageId}`,

    getAbout: () => request<AboutView>("/api/about"),
    getDay: (day) =>
      request<DevDayDetail>(
        `/api/dev/day?day=${encodeURIComponent(day)}`,
        authorized(token()),
      ),
    getSchedule: () =>
      request<DevSchedule>("/api/dev/schedule", authorized(token())),
    setPause: (paused, note) =>
      request<DevSchedule>(
        "/api/dev/rollover/pause",
        authorized(token(), jsonBody({ paused, note })),
      ),
    runRollover: () =>
      request<DevRolloverResult>(
        "/api/dev/rollover/run",
        authorized(token(), { method: "POST" }),
      ),
    getPlayer: (player) =>
      request<DevPlayerDetail>(playerPath(player), authorized(token())),
    getAvatar: async (player) => {
      // An <img> cannot send the bearer, so the bytes come through
      // fetch and the caller shows them from an object URL.
      const response = await send(
        `${playerPath(player)}/avatar`,
        authorized(token()),
      );
      if (response.status === 404) {
        return null;
      }
      if (!response.ok) {
        throw new DevApiError(response.status, "the picture did not load");
      }
      return response.blob();
    },
    rotatePlayer: (player) =>
      request<MintedInvite>(
        `${playerPath(player)}/rotate`,
        authorized(token(), { method: "POST" }),
      ),
    restorePlayer: (player) =>
      request<MintedInvite>(
        `${playerPath(player)}/restore`,
        authorized(token(), { method: "POST" }),
      ),
    revokePlayer: (player) =>
      request(
        `${playerPath(player)}/revoke`,
        authorized(token(), { method: "POST" }),
      ),
    signOutPlayer: (player) =>
      request(
        `${playerPath(player)}/signout`,
        authorized(token(), { method: "POST" }),
      ),
    endSession: (player, sessionId) =>
      request(
        `${playerPath(player)}/sessions/${encodeURIComponent(sessionId)}`,
        authorized(token(), { method: "DELETE" }),
      ),
    issueDeviceCode: (player) =>
      request<DevDeviceCode>(
        `${playerPath(player)}/device-code`,
        authorized(token(), { method: "POST" }),
      ),
    prune: () =>
      request("/api/dev/prune", authorized(token(), { method: "POST" })),
    getIndex: () =>
      request<DevIndexStatus>("/api/dev/index", authorized(token())),
    buildIndex: () =>
      request<DevIndexStatus>(
        "/api/dev/index/build",
        authorized(token(), { method: "POST" }),
      ),
    verifyIndex: () =>
      request<DevIndexCheck>(
        "/api/dev/index/verify",
        authorized(token(), { method: "POST" }),
      ),
    queryIndex: (sql) =>
      request<DevQueryResult>(
        "/api/dev/index/query",
        authorized(token(), jsonBody({ sql })),
      ),
  };
}

function playerPath(player: string): string {
  return `/api/dev/players/${encodeURIComponent(player)}`;
}

function jsonBody(value: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(value),
  };
}
