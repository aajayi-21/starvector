/**
 * The on-screen rule checks for a username, a password, and a recovery
 * code (spec A2 §4.1, §5.1, §6). Pure functions of strings.
 *
 * The server owns each rule (service/names.py, service/passwords.py)
 * and refuses what it does not accept. These checks mirror the rules a
 * screen can show while the player types, so a refusal is rare. Two
 * rules have no mirror here, because the screen does not hold their
 * tables: the reserved names and the commonly used passwords.
 */

/** Spec A2 decision D1. */
export const USERNAME_MIN = 3;
export const USERNAME_MAX = 20;
/** Spec A2 ruling 4 and decision D3. */
export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;
/** Spec A2 decision D8: 24 characters, shown as six groups of four. */
export const RECOVERY_CODE_LENGTH = 24;
/** The device-code alphabet: no 0, O, 1, I, or L (spec A2 §6). */
export const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

export interface RuleCheck {
  /** A stable key for the list. */
  id: string;
  /** The rule, in the words the screen shows. */
  label: string;
  ok: boolean;
}

/**
 * A typed username with its capitals as small letters.
 *
 * A to Z alone, as the server does: toLowerCase also turns some
 * characters of other scripts into ASCII letters, and such a
 * character must stay illegal.
 */
export function normalizeUsername(typed: string): string {
  return typed.replace(/[A-Z]/g, (capital) => capital.toLowerCase());
}

/** Each username rule with its state, in the sequence the screen lists. */
export function usernameChecks(name: string): RuleCheck[] {
  return [
    {
      id: "length",
      label: `${USERNAME_MIN} to ${USERNAME_MAX} characters`,
      ok: name.length >= USERNAME_MIN && name.length <= USERNAME_MAX,
    },
    {
      id: "alphabet",
      label: "Only the letters a to z, the digits 0 to 9, and the hyphen",
      ok: /^[a-z0-9-]+$/.test(name),
    },
    {
      id: "first",
      label: "Starts with a letter",
      ok: /^[a-z]/.test(name),
    },
    {
      id: "hyphens",
      label: "No hyphen at the end, and no two hyphens together",
      ok: name !== "" && !name.endsWith("-") && !name.includes("--"),
    },
  ];
}

/** Each password rule a screen can check, with its state. */
export function passwordChecks(
  password: string,
  username: string,
): RuleCheck[] {
  // The server counts code points after NFKC, and so does this.
  const shape = password.normalize("NFKC");
  const length = [...shape].length;
  const checks: RuleCheck[] = [
    {
      id: "length",
      label: `${PASSWORD_MIN} to ${PASSWORD_MAX} characters`,
      ok: length >= PASSWORD_MIN && length <= PASSWORD_MAX,
    },
  ];
  if (username !== "") {
    checks.push({
      id: "username",
      label: "Does not contain your username",
      ok: shape !== "" && !shape.toLowerCase().includes(username),
    });
  }
  return checks;
}

export function allOk(checks: ReadonlyArray<RuleCheck>): boolean {
  return checks.every((check) => check.ok);
}

/**
 * The folded shape of a username (spec A2 §4.2): each hyphen goes, 0
 * becomes o, and 1 becomes l. Two names with one folded shape are one
 * name. The mock adapter uses it for the name-taken refusal.
 */
export function foldedName(name: string): string {
  return name.replaceAll("-", "").replaceAll("0", "o").replaceAll("1", "l");
}

/**
 * A typed recovery code with no spaces and no hyphens, in capitals.
 * Capitals, spaces, and hyphens do not count when a player types it.
 */
export function compactRecoveryCode(typed: string): string {
  return typed.replaceAll(/[\s-]/g, "").toUpperCase();
}

/** True when the typed text has the shape of a recovery code. */
export function isRecoveryCodeShape(typed: string): boolean {
  const compact = compactRecoveryCode(typed);
  return (
    compact.length === RECOVERY_CODE_LENGTH &&
    [...compact].every((character) => CODE_ALPHABET.includes(character))
  );
}

/** 24 characters → "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2". */
export function displayRecoveryCode(code: string): string {
  const groups: string[] = [];
  for (let start = 0; start < code.length; start += 4) {
    groups.push(code.slice(start, start + 4));
  }
  return groups.join("-");
}
