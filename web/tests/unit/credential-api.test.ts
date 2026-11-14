import { afterEach, describe, expect, it, vi } from "vitest";

import { makeRealApi } from "../../src/api/real";
import {
  ApiError,
  credentialMessage,
  friendlyMessage,
} from "../../src/api/types";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

type Call = [string, RequestInit | undefined];

/** Records each fetch and answers one JSON body. */
function answering(status: number, body: unknown): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => {
    calls.push([url, init]);
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  return calls;
}

function sent(call: Call | undefined): {
  url: string;
  method: string | undefined;
  mediaType: string | undefined;
  body: unknown;
} {
  if (call === undefined) {
    throw new Error("no call was made");
  }
  const [url, init] = call;
  const headers = init?.headers as Record<string, string> | undefined;
  return {
    url,
    method: init?.method,
    mediaType: headers?.["Content-Type"],
    body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
  };
}

const CODE = "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2";

describe("the credential calls of the live client (spec A2 §8)", () => {
  it("reads if the server makes accounts", async () => {
    const calls = answering(200, { open: true });
    expect(await makeRealApi().getSignup()).toEqual({ open: true });
    expect(sent(calls[0])).toMatchObject({
      url: "/api/signup",
      method: undefined,
    });
  });

  it("reads a closed sign-up as the constant 404", async () => {
    answering(404, { detail: "not found" });
    await expect(makeRealApi().getSignup()).rejects.toMatchObject({
      status: 404,
    });
  });

  it("posts each credential as JSON, with its media type, in the body", async () => {
    const calls = answering(200, {});
    const api = makeRealApi();
    await api.signUp("nova", "a pass phrase");
    await api.signIn("nova", "a pass phrase");
    await api.recover("nova", CODE, "a new pass phrase");
    await api.setPassword("a new pass phrase", "a pass phrase");
    await api.newRecoveryCode("a pass phrase");
    expect(calls.map(sent)).toEqual([
      {
        url: "/api/signup",
        method: "POST",
        mediaType: "application/json",
        body: { username: "nova", password: "a pass phrase" },
      },
      {
        url: "/api/signin",
        method: "POST",
        mediaType: "application/json",
        body: { username: "nova", password: "a pass phrase" },
      },
      {
        url: "/api/recover",
        method: "POST",
        mediaType: "application/json",
        body: {
          username: "nova",
          recovery_code: CODE,
          password: "a new pass phrase",
        },
      },
      {
        url: "/api/account/password",
        method: "POST",
        mediaType: "application/json",
        body: {
          current_password: "a pass phrase",
          password: "a new pass phrase",
        },
      },
      {
        url: "/api/account/recovery-code",
        method: "POST",
        mediaType: "application/json",
        body: { current_password: "a pass phrase" },
      },
    ]);
    // No credential is in an address (spec A2 §5.3).
    for (const [url] of calls) {
      expect(url).not.toContain("?");
      expect(url).not.toContain("phrase");
    }
  });

  it("leaves current_password out of a first password", async () => {
    const calls = answering(200, {
      changed: true,
      signed_out: 0,
      recovery_code: CODE,
    });
    const answer = await makeRealApi().setPassword("a new pass phrase");
    expect(sent(calls[0]).body).toEqual({ password: "a new pass phrase" });
    expect(answer.recovery_code).toBe(CODE);
  });

  it("stops the operator's code with a POST and no body", async () => {
    const calls = answering(200, { stopped: true });
    expect(await makeRealApi().stopOperatorCode()).toEqual({ stopped: true });
    const [url, init] = calls[0] as Call;
    expect(url).toBe("/api/account/recovery-code/stop");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBeUndefined();
  });

  it("returns the recovery code of a sign-up and of a recovery", async () => {
    answering(201, {
      player: "nova",
      display_name: "nova",
      recovery_code: CODE,
    });
    const api = makeRealApi();
    expect((await api.signUp("nova", "a pass phrase")).recovery_code).toBe(
      CODE,
    );
    expect(
      (await api.recover("nova", CODE, "a new pass phrase")).recovery_code,
    ).toBe(CODE);
  });

  it("throws the cause of each refusal", async () => {
    const cases: Array<[number, string, () => Promise<unknown>]> = [
      [400, "name-rule", () => makeRealApi().signUp("x", "y")],
      [409, "name-taken", () => makeRealApi().signUp("x", "y")],
      [401, "sign-in", () => makeRealApi().signIn("x", "y")],
      [401, "recovery", () => makeRealApi().recover("x", CODE, "y")],
      [403, "password", () => makeRealApi().setPassword("y", "z")],
      [429, "too-many-attempts", () => makeRealApi().signIn("x", "y")],
    ];
    for (const [status, cause, call] of cases) {
      answering(status, { cause });
      await expect(call()).rejects.toMatchObject({
        status,
        refusalCause: cause,
      });
    }
  });
});

describe("the words for each credential refusal", () => {
  const CAUSES: Array<[number, string]> = [
    [400, "name-rule"],
    [400, "name-reserved"],
    [409, "name-taken"],
    [400, "password-rule"],
    [400, "password-usual"],
    [401, "sign-in"],
    [401, "recovery"],
    [403, "password"],
    [403, "origin"],
    [429, "too-many-attempts"],
  ];

  it("maps each cause to a sentence and never shows the cause token", () => {
    const seen = new Set<string>();
    for (const [status, cause] of CAUSES) {
      const copy = friendlyMessage(new ApiError(status, cause));
      expect(copy).not.toBe("Something went wrong. Try again.");
      // A token with a hyphen is no English word, thus it must not
      // show. "recovery" and "password" are words the copy needs.
      if (cause.includes("-")) {
        expect(copy).not.toContain(cause);
      }
      expect(copy).toMatch(/\.$/);
      seen.add(copy);
    }
    // Each cause has its own sentence.
    expect(seen.size).toBe(CAUSES.length);
  });

  it("does not say which of the username and the password was wrong", () => {
    expect(friendlyMessage(new ApiError(401, "sign-in"))).toBe(
      "The username or the password is wrong.",
    );
  });

  it("names the rule a refused name or password broke", () => {
    expect(friendlyMessage(new ApiError(400, "name-rule"))).toMatch(
      /3 to 20 characters/,
    );
    expect(friendlyMessage(new ApiError(400, "name-reserved"))).toMatch(
      /reserved/,
    );
    expect(friendlyMessage(new ApiError(409, "name-taken"))).toMatch(/taken/);
    expect(friendlyMessage(new ApiError(400, "password-rule"))).toMatch(
      /12 to 128 characters/,
    );
    expect(friendlyMessage(new ApiError(400, "password-usual"))).toMatch(
      /many people use/,
    );
    expect(friendlyMessage(new ApiError(403, "password"))).toMatch(
      /current password/,
    );
  });

  it("says to wait on a 429", () => {
    expect(friendlyMessage(new ApiError(429, "too-many-attempts"))).toMatch(
      /Wait a few minutes, then try again/,
    );
  });

  it("reads the constant 404 as a server with no password sign-in", () => {
    expect(credentialMessage(new ApiError(404, undefined, "not found"))).toBe(
      "This server doesn't use usernames and passwords.",
    );
    // Each other refusal keeps its own sentence.
    expect(credentialMessage(new ApiError(401, "sign-in"))).toBe(
      "The username or the password is wrong.",
    );
    expect(credentialMessage(new ApiError(0))).toMatch(/Can't reach/);
  });
});
