import { afterEach, describe, expect, it, vi } from "vitest";

import { makeDevApi } from "../../src/dev/api";

afterEach(() => {
  vi.restoreAllMocks();
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
