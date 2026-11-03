import { afterEach, describe, expect, it, vi } from "vitest";

import { DevApiError, makeDevApi, OLDER_SERVER } from "../../src/dev/api";
import { refusedRead } from "../../src/dev/controls";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** Records every fetch and answers an empty JSON body. */
function watching(): Array<[string, RequestInit | undefined]> {
  const calls: Array<[string, RequestInit | undefined]> = [];
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    return Promise.resolve(
      new Response("{}", {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  return calls;
}

function headerOf(init: RequestInit | undefined): string | undefined {
  return (init?.headers as Record<string, string> | undefined)?.Authorization;
}

describe("the console's client", () => {
  it("sends the operator token on every call", async () => {
    const calls = watching();
    const api = makeDevApi(() => "a-token");
    await api.getDays();
    await api.getSubmission("2026-08-12");
    await api.getRankings("2026-08-12");
    await api.postOpen();
    await api.postClose();
    await api.postReveal();
    expect(calls).toHaveLength(6);
    for (const [, init] of calls) {
      expect(headerOf(init)).toBe("Bearer a-token");
    }
    // The lifecycle calls keep their method.
    expect(calls.slice(3).map(([, init]) => init?.method)).toEqual([
      "POST",
      "POST",
      "POST",
    ]);
  });

  it("sends no header at all with no token", async () => {
    // Ruling 7 of spec M1: with no player stored nothing holds
    // credentials and the operator plane answers as it always did.
    // An empty bearer would be a header the server has to refuse.
    const calls = watching();
    await makeDevApi(() => "").getDays();
    await makeDevApi().postOpen();
    for (const [, init] of calls) {
      expect(headerOf(init)).toBeUndefined();
    }
  });

  it("reads the token at call time, not at wiring time", async () => {
    // The operator pastes a token into a console that is already
    // running. A captured token would need the page reloaded.
    const calls = watching();
    let token = "first";
    const api = makeDevApi(() => token);
    await api.getDays();
    token = "second";
    await api.getDays();
    expect(calls.map(([, init]) => headerOf(init))).toEqual([
      "Bearer first",
      "Bearer second",
    ]);
  });
});

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("the console client after the review (spec BR1 §7.6)", () => {
  it("names an older server when a console path does not exist there", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => answer(404, { detail: "Not Found" })),
    );
    const error = await makeDevApi()
      .getPlayer("ade")
      .catch((failure: unknown) => failure);
    expect(error).toBeInstanceOf(DevApiError);
    expect((error as DevApiError).message).toBe(OLDER_SERVER);
    expect(refusedRead(error)).toBe(OLDER_SERVER);
  });

  it("keeps the dev-gate wording for the server's own 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => answer(404, { detail: "not found" })),
    );
    const error = await makeDevApi()
      .getSchedule()
      .catch((failure: unknown) => failure);
    expect(refusedRead(error)).toMatch(/start the server with --dev/);
  });

  it("sends the named day in the body of a named move", async () => {
    const fetch = vi.fn(async () => answer(200, { day: "2026-08-14" }));
    vi.stubGlobal("fetch", fetch);
    await makeDevApi(() => "a-token").revealDay("2026-08-14");
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/dev/day/reveal");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ day: "2026-08-14" }));
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer a-token",
    );
  });
});
