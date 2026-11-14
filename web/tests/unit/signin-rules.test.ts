import { describe, expect, it } from "vitest";

import {
  allOk,
  compactRecoveryCode,
  displayRecoveryCode,
  foldedName,
  isRecoveryCodeShape,
  normalizeUsername,
  passwordChecks,
  usernameChecks,
} from "../../src/signin/rules";

/** The ids of the rules a value does not meet. */
function failing(checks: ReturnType<typeof usernameChecks>): string[] {
  return checks.filter((check) => !check.ok).map((check) => check.id);
}

describe("the username rules on screen (spec A2 §4.1)", () => {
  it("changes typed capitals to small letters, A to Z alone", () => {
    expect(normalizeUsername("Quiet-Signal7")).toBe("quiet-signal7");
    // A capital of a different script stays as typed, and thus stays
    // illegal: toLowerCase would not be the server's map.
    expect(normalizeUsername("İstanbul")).toBe("İstanbul");
    expect(allOk(usernameChecks(normalizeUsername("İstanbul")))).toBe(false);
  });

  it("accepts the legal shapes", () => {
    for (const name of [
      "abc",
      "a-b",
      "quiet-signal-7",
      "a2345678901234567890",
    ]) {
      expect(failing(usernameChecks(name))).toEqual([]);
    }
  });

  it("names the rule that each bad name breaks", () => {
    const cases: Array<[string, string[]]> = [
      ["", ["length", "alphabet", "first", "hyphens"]],
      ["ab", ["length"]],
      ["a23456789012345678901", ["length"]],
      ["has space", ["alphabet"]],
      ["under_score", ["alphabet"]],
      ["Capital", ["alphabet", "first"]],
      ["9lives", ["first"]],
      ["-dash", ["first"]],
      ["ends-", ["hyphens"]],
      ["two--hyphens", ["hyphens"]],
    ];
    for (const [name, broken] of cases) {
      expect(failing(usernameChecks(name))).toEqual(broken);
    }
  });

  it("folds look-alike names to one shape (§4.2)", () => {
    expect(foldedName("no-one")).toBe("noone");
    expect(foldedName("n0one")).toBe("noone");
    expect(foldedName("a1-b")).toBe("alb");
  });
});

describe("the password rules on screen (spec A2 §5.1)", () => {
  it("wants 12 to 128 characters and no character class", () => {
    expect(failing(passwordChecks("elevenchars", "nova"))).toEqual(["length"]);
    // All small letters, with spaces: no capital, digit, or symbol.
    expect(failing(passwordChecks("twelve chars", "nova"))).toEqual([]);
    expect(failing(passwordChecks("x".repeat(128), "nova"))).toEqual([]);
    expect(failing(passwordChecks("x".repeat(129), "nova"))).toEqual([
      "length",
    ]);
  });

  it("counts code points, after NFKC, as the server does", () => {
    // 12 emoji are 12 code points and 24 UTF-16 units.
    expect(failing(passwordChecks("🌊".repeat(12), "nova"))).toEqual([]);
    expect(failing(passwordChecks("🌊".repeat(11), "nova"))).toEqual([
      "length",
    ]);
    // One ligature character is two letters after NFKC.
    expect(failing(passwordChecks(`${"x".repeat(10)}ﬁ`, "nova"))).toEqual([]);
  });

  it("refuses a password that holds the username, in each mix of capitals", () => {
    expect(failing(passwordChecks("my name is NoVa ok", "nova"))).toEqual([
      "username",
    ]);
    expect(failing(passwordChecks("a long quiet phrase", "nova"))).toEqual([]);
  });

  it("lists no username rule before a username is typed", () => {
    const checks = passwordChecks("a long quiet phrase", "");
    expect(checks.map((check) => check.id)).toEqual(["length"]);
  });
});

describe("the recovery code as typed (spec A2 §6)", () => {
  const shown = "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2";

  it("shows six groups of four", () => {
    expect(displayRecoveryCode("ABCDEFGHJKMNPQRSTUVWXYZ2")).toBe(shown);
  });

  it("does not count capitals, spaces, or hyphens", () => {
    expect(compactRecoveryCode(" abcd efgh-jkmn  pqrs-tuvw xyz2 ")).toBe(
      "ABCDEFGHJKMNPQRSTUVWXYZ2",
    );
    expect(isRecoveryCodeShape(shown)).toBe(true);
    expect(isRecoveryCodeShape(shown.toLowerCase().replaceAll("-", " "))).toBe(
      true,
    );
  });

  it("refuses a wrong length and a character outside the alphabet", () => {
    expect(isRecoveryCodeShape("ABCD-EFGH")).toBe(false);
    // 0, O, 1, I, and L are not in the alphabet.
    expect(isRecoveryCodeShape("0BCD-EFGH-JKMN-PQRS-TUVW-XYZ2")).toBe(false);
    expect(isRecoveryCodeShape("LBCD-EFGH-JKMN-PQRS-TUVW-XYZ2")).toBe(false);
  });
});
