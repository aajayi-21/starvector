import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { MOCK_PASSWORD, makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import {
  NOTICE_BODY,
  NOTICE_LEAD,
  NOTICE_VERSION,
} from "../../src/signin/notice";
import { MOCK_PROOF } from "../../src/signin/proof-field";
import { HARNESS_TODAY, renderAt } from "./harness";

const GOOD = "four quiet amber lanterns";

/** The mock, signed out, with the dev door off: the gate alone. */
function signedOut(overrides: Partial<Api> = {}): Api {
  return {
    ...makeMockApi({ today: HARNESS_TODAY, signedIn: false }),
    getDoor: () => Promise.reject(new ApiError(404, undefined, "not found")),
    ...overrides,
  };
}

function type(label: string | RegExp, value: string): HTMLInputElement {
  const field = screen.getByLabelText(label) as HTMLInputElement;
  fireEvent.change(field, { target: { value } });
  return field;
}

function button(name: string): HTMLButtonElement {
  return screen.getByRole("button", { name }) as HTMLButtonElement;
}

const NAME_SUMMARY =
  "3 to 20 letters, numbers, or hyphens, starting with a letter";
const WORD_SUMMARY = "At least 12 characters. A few unrelated words work well.";

/** The element that describes a field: its one helper line. */
function helperLine(label: string): HTMLElement {
  const field = screen.getByLabelText(label);
  return document.getElementById(
    field.getAttribute("aria-describedby") ?? "",
  ) as HTMLElement;
}

/** The words of a field's helper line, and the state the screen marks. */
function helper(label: string): {
  text: string;
  state: "neutral" | "met" | "broken";
} {
  const line = helperLine(label);
  return {
    text: line.textContent ?? "",
    state: line.className.includes("rule-hint-broken")
      ? "broken"
      : line.className.includes("rule-hint-met")
        ? "met"
        : "neutral",
  };
}

/** The progress line of a sign-up, or null when the screen has none. */
function progress(): Array<{ text: string; current: boolean }> | null {
  const line = screen.queryByRole("list", { name: "Creating your account" });
  return line === null
    ? null
    : within(line)
        .getAllByRole("listitem")
        .map((part) => ({
          text: part.textContent ?? "",
          current: part.getAttribute("aria-current") === "step",
        }));
}

describe("the gate screen (spec A2 §3)", () => {
  it("shows the three controls when the server makes accounts", async () => {
    renderAt("/", signedOut());
    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeDefined();
    expect(button("Sign in")).toBeDefined();
    expect(
      await screen.findByRole("button", { name: "Create an account" }),
    ).toBeDefined();
    expect(button("Forgot it?")).toBeDefined();
    // The device code stays: the way in with no password to type.
    expect(screen.getByLabelText("Device code")).toBeDefined();
    expect(screen.queryByText(/invite/i)).toBeNull();
    // A sign-in has no parts to show.
    expect(progress()).toBeNull();
  });

  it("holds each way in in the one card, the quiet ones as closed rows", async () => {
    renderAt("/", signedOut());
    const heading = await screen.findByRole("heading", { name: "Sign in" });
    const card = heading.closest("section") as HTMLElement;
    // `Forgot it?` comes after the password in the document, thus Tab
    // goes from the password to it.
    const forgot = button("Forgot it?");
    expect(forgot.type).toBe("button");
    expect(
      screen.getByLabelText("Password").compareDocumentPosition(forgot) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    // The device code is a row of the card, closed until it is opened.
    const row = screen
      .getByText("Use a code from another device")
      .closest("details") as HTMLDetailsElement;
    expect(card.contains(row)).toBe(true);
    expect(row.open).toBe(false);
    const code = within(row).getByLabelText("Device code");
    const facts = document.getElementById(
      code.getAttribute("aria-describedby") ?? "",
    ) as HTMLElement;
    expect(facts.textContent).toMatch(/choose “Add a device”/);
    expect(facts.textContent).toMatch(/8-character code/);
    expect(facts.textContent).toMatch(/won't need your password/);
    // No dev door on this server, thus no operator row.
    expect(screen.queryByText("Operator sign-in")).toBeNull();
    expect(screen.queryByText("Test server")).toBeNull();
  });

  it("adds the operator row on a test server, with its sign", async () => {
    renderAt(
      "/",
      signedOut({ getDoor: () => Promise.resolve({ open: true }) }),
    );
    const title = await screen.findByText("Operator sign-in");
    const row = title.closest("details") as HTMLDetailsElement;
    const card = screen
      .getByRole("heading", { name: "Sign in" })
      .closest("section") as HTMLElement;
    expect(card.contains(row)).toBe(true);
    expect(row.open).toBe(false);
    const summary = row.querySelector("summary") as HTMLElement;
    expect(within(summary).getByText("Test server").className).toContain(
      "badge-warn",
    );
    expect(row.textContent).toMatch(/This is a test server/);
    expect(row.textContent).toMatch(/operator\s+token instead of a password/);
    expect(row.textContent).toMatch(/Real servers don't show this/);
    expect(within(row).getByLabelText("Player name")).toBeDefined();
    expect(within(row).getByLabelText("Operator token")).toBeDefined();
  });

  it("signs in with a device code from its row", async () => {
    const codes: string[] = [];
    const base = signedOut();
    renderAt(
      "/",
      signedOut({
        ...base,
        redeemDeviceCode: async (code) => {
          codes.push(code);
          // A session of the mock's first player, as a good code gives.
          await base.signIn("ade", MOCK_PASSWORD);
          return { player: "ade", display_name: "ade" };
        },
      }),
    );
    const title = await screen.findByText("Use a code from another device");
    const row = title.closest("details") as HTMLDetailsElement;
    fireEvent.click(title);
    const field = within(row).getByLabelText("Device code");
    const submit = within(row).getByText("Use this code") as HTMLButtonElement;
    expect(submit.type).toBe("submit");
    expect(submit.disabled).toBe(true);
    fireEvent.change(field, { target: { value: "abcd-efgh" } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() => expect(codes).toEqual(["abcd-efgh"]));
    expect(await screen.findByText(/Today's photo is hidden/)).toBeDefined();
  });

  it("signs the operator in by name from its row", async () => {
    const doors: Array<[string, string | undefined]> = [];
    const base = signedOut();
    renderAt(
      "/",
      signedOut({
        ...base,
        getDoor: () => Promise.resolve({ open: true }),
        postDoor: (name, label, token) => {
          doors.push([name, token]);
          return base.postDoor(name, label, token);
        },
      }),
    );
    const title = await screen.findByText("Operator sign-in");
    const row = title.closest("details") as HTMLDetailsElement;
    fireEvent.click(title);
    const submit = within(row).getByText(
      "Sign in by name",
    ) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(row).getByLabelText("Player name"), {
      target: { value: "walkin" },
    });
    fireEvent.change(within(row).getByLabelText("Operator token"), {
      target: { value: "token" },
    });
    fireEvent.click(submit);
    expect(await screen.findByText(/, walkin$/)).toBeDefined();
    expect(doors).toEqual([["walkin", "token"]]);
  });

  it("says a test season is a test season, by the headline", async () => {
    renderAt("/", signedOut());
    // The shell shows its own season badge while it reads me: wait for
    // the gate.
    await screen.findByRole("heading", { name: "Sign in" });
    const badge = await screen.findByText("Test season");
    expect(badge.className).toContain("badge-warn");
    const note = badge.closest('[role="note"]') as HTMLElement;
    expect(note.textContent).toMatch(
      /Results won't carry over to the public launch\./,
    );
    // Adjacent to the headline, and not a strip above the page.
    const headline = screen.getByRole("heading", { level: 1 });
    expect(headline.parentElement?.contains(note)).toBe(true);
    expect(document.querySelector(".season-note")).toBeNull();
  });

  it("offers no new account when sign-up answers the constant 404", async () => {
    renderAt(
      "/",
      signedOut({
        getSignup: () =>
          Promise.reject(new ApiError(404, undefined, "not found")),
      }),
    );
    expect(
      await screen.findByText("This server isn't making new accounts now."),
    ).toBeDefined();
    expect(
      screen.queryByRole("button", { name: "Create an account" }),
    ).toBeNull();
    // Sign-in and recovery stay for each account the store holds.
    expect(button("Sign in")).toBeDefined();
    expect(button("Forgot it?")).toBeDefined();
  });

  it("reads the sign-up switch one time", async () => {
    let reads = 0;
    const base = signedOut();
    renderAt(
      "/",
      signedOut({
        getSignup: () => {
          reads += 1;
          return base.getSignup();
        },
      }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Create an account" }),
    );
    fireEvent.click(button("Back to sign in"));
    fireEvent.click(button("Forgot it?"));
    fireEvent.click(button("Back to sign in"));
    expect(reads).toBe(1);
    // A sign-in starts the app's reads again, and not this one.
    type("Username", "ade");
    type("Password", MOCK_PASSWORD);
    fireEvent.click(button("Sign in"));
    await screen.findByText(/Today's photo is hidden/);
    expect(reads).toBe(1);
  });
});

describe("sign-in (spec A2 §3.2)", () => {
  it("signs in with a username and a password and shows the app", async () => {
    const pairs: Array<[string, string]> = [];
    const base = signedOut();
    renderAt(
      "/",
      signedOut({
        ...base,
        signIn: (username, password) => {
          pairs.push([username, password]);
          return base.signIn(username, password);
        },
      }),
    );
    await screen.findByRole("heading", { name: "Sign in" });
    expect(button("Sign in").disabled).toBe(true);
    // Typed capitals become small letters before the POST.
    const name = type("Username", "ADE");
    expect(name.value).toBe("ade");
    type("Password", MOCK_PASSWORD);
    expect(button("Sign in").disabled).toBe(false);
    fireEvent.click(button("Sign in"));
    expect(await screen.findByText(/Today's photo is hidden/)).toBeDefined();
    expect(pairs).toEqual([["ade", MOCK_PASSWORD]]);
  });

  it("says the pair is wrong and not which half", async () => {
    renderAt("/", signedOut());
    await screen.findByRole("heading", { name: "Sign in" });
    type("Username", "ade");
    type("Password", "not the password");
    fireEvent.click(button("Sign in"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("The username or the password is wrong.");
    // Still signed out, with the typed username kept.
    expect(screen.queryByRole("navigation")).toBeNull();
    expect((screen.getByLabelText("Username") as HTMLInputElement).value).toBe(
      "ade",
    );
  });

  it("says to wait on a 429", async () => {
    renderAt(
      "/",
      signedOut({
        signIn: () => Promise.reject(new ApiError(429, "too-many-attempts")),
      }),
    );
    await screen.findByRole("heading", { name: "Sign in" });
    type("Username", "ade");
    type("Password", MOCK_PASSWORD);
    fireEvent.click(button("Sign in"));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /Wait a few minutes, then try again/,
    );
  });

  it("says so on a server with no password sign-in", async () => {
    renderAt(
      "/",
      signedOut({
        signIn: () => Promise.reject(new ApiError(404, undefined, "not found")),
      }),
    );
    await screen.findByRole("heading", { name: "Sign in" });
    type("Username", "ade");
    type("Password", MOCK_PASSWORD);
    fireEvent.click(button("Sign in"));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "This server doesn't use usernames and passwords.",
    );
  });

  it("lets a password manager fill it, and shows the password on request", async () => {
    renderAt("/", signedOut());
    await screen.findByRole("heading", { name: "Sign in" });
    const name = screen.getByLabelText("Username") as HTMLInputElement;
    const word = screen.getByLabelText("Password") as HTMLInputElement;
    // One real form holds the two fields and a submit button.
    expect(name.form).not.toBeNull();
    expect(word.form).toBe(name.form);
    expect(button("Sign in").type).toBe("submit");
    expect(name.autocomplete).toBe("username");
    expect(word.autocomplete).toBe("current-password");
    expect(word.type).toBe("password");
    // No handler stops a paste, and no length cuts a password short.
    expect(word.maxLength).toBe(-1);
    const show = button("Show Password");
    expect(show.getAttribute("aria-pressed")).toBe("false");
    expect(show.type).toBe("button");
    fireEvent.click(show);
    expect(word.type).toBe("text");
    expect(button("Hide Password").getAttribute("aria-pressed")).toBe("true");
  });
});

describe("make an account (spec A2 §3.1)", () => {
  async function openSignUp(api: Api): Promise<void> {
    renderAt("/", api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Create an account" }),
    );
    await screen.findByRole("heading", { name: "Create an account" });
  }

  it("shows the summary of each field's rules before the player types", async () => {
    await openSignUp(signedOut());
    expect(helper("Username")).toEqual({
      text: NAME_SUMMARY,
      state: "neutral",
    });
    expect(helper("Password")).toEqual({
      text: WORD_SUMMARY,
      state: "neutral",
    });
    expect(screen.getByText("Capital letters become lowercase.")).toBeDefined();
    expect(button("Create account").disabled).toBe(true);
  });

  it("names each broken username rule in the helper line", async () => {
    await openSignUp(signedOut());
    const cases: Array<[string, string]> = [
      ["no", "Use 3 to 20 characters."],
      ["a23456789012345678901", "Use 3 to 20 characters."],
      ["under_score", "Letters a to z, numbers, and hyphens only."],
      ["9lives", "Start with a letter."],
      ["nova-", "No hyphen at the end, and no two hyphens in a row."],
      ["no--va", "No hyphen at the end, and no two hyphens in a row."],
      // Each broken rule shows, in the sequence of the rules.
      [
        "9_",
        "Use 3 to 20 characters. Letters a to z, numbers, and hyphens only. " +
          "Start with a letter.",
      ],
    ];
    for (const [name, broken] of cases) {
      type("Username", name);
      expect(helper("Username")).toEqual({ text: broken, state: "broken" });
      expect(button("Create account").disabled).toBe(true);
    }
    // Typed capitals become small letters, and the rules read those.
    const name = type("Username", "Nova-");
    expect(name.value).toBe("nova-");
    expect(helper("Username").state).toBe("broken");
    // Each rule met: the summary again, marked met.
    type("Username", "nova");
    expect(helper("Username")).toEqual({
      text: `${NAME_SUMMARY} (met)`,
      state: "met",
    });
    // An empty field goes back to the summary, with no error.
    type("Username", "");
    expect(helper("Username")).toEqual({
      text: NAME_SUMMARY,
      state: "neutral",
    });
  });

  it("names each broken password rule in the helper line", async () => {
    await openSignUp(signedOut());
    type("Username", "nova");
    const cases: Array<[string, string]> = [
      ["elevenchars", "Use at least 12 characters."],
      ["x".repeat(129), "Use no more than 128 characters."],
      // The password must not hold the username.
      ["nova nova nova nova", "Don't include your username."],
      ["nova", "Use at least 12 characters. Don't include your username."],
    ];
    for (const [word, broken] of cases) {
      type("Password", word);
      expect(helper("Password")).toEqual({ text: broken, state: "broken" });
      expect(button("Create account").disabled).toBe(true);
    }
    type("Password", GOOD);
    expect(helper("Password")).toEqual({
      text: `${WORD_SUMMARY} (met)`,
      state: "met",
    });
    expect(button("Create account").disabled).toBe(false);
  });

  it("names the usual-password rule when the server refuses for it", async () => {
    // The screen does not hold the table of usual passwords: the rule
    // shows in the helper line after the server's refusal.
    await openSignUp(
      signedOut({
        signUp: () => Promise.reject(new ApiError(400, "password-usual")),
      }),
    );
    type("Username", "nova");
    type("Password", GOOD);
    expect(helper("Password").state).toBe("met");
    fireEvent.click(button("Create account"));
    expect((await screen.findByRole("alert")).textContent).toMatch(
      /one many people use/,
    );
    expect(helper("Password")).toEqual({
      text: "Don't use a password that many people use.",
      state: "broken",
    });
    // The line is for the refused password alone.
    type("Password", "five slow north harbors");
    expect(helper("Password").state).toBe("met");
    type("Password", GOOD);
    expect(helper("Password").state).toBe("broken");
  });

  it("ties each helper line to its field, with the state in words", async () => {
    await openSignUp(signedOut());
    const rules = helperLine("Username");
    // A polite live region: a screen reader says the line when it changes.
    expect(rules.getAttribute("aria-live")).toBe("polite");
    expect(within(rules).queryByText("(met)")).toBeNull();
    type("Username", "nova");
    expect(within(rules).getByText("(met)")).toBeDefined();
    const word = screen.getByLabelText("Password") as HTMLInputElement;
    expect(word.autocomplete).toBe("new-password");
    expect(helperLine("Password").getAttribute("aria-live")).toBe("polite");
  });

  it("says what a username is before the account is made", async () => {
    await openSignUp(signedOut());
    // The season line is a note too: this one is in the form.
    const note = screen
      .getByText(/Everyone sees this name/)
      .closest('[role="note"]') as HTMLElement;
    expect(note.closest("form")).not.toBeNull();
    expect(note.className).toContain("notice-warn");
    expect(note.textContent).toMatch(/Everyone sees this name/);
    expect(note.textContent).toMatch(/can never be changed/);
    expect(note.textContent).toMatch(/Don't use your\s+real name/);
  });

  it("shows the parts of a sign-up above the card", async () => {
    await openSignUp(signedOut());
    expect(progress()).toEqual([
      { text: "Name and password", current: true },
      { text: "Recovery code", current: false },
      { text: "Your first day", current: false },
    ]);
    // The line is above the card, and not in it.
    const line = screen.getByRole("list", { name: "Creating your account" });
    const card = screen
      .getByRole("heading", { name: "Create an account" })
      .closest("section") as HTMLElement;
    expect(card.contains(line)).toBe(false);
    expect(
      line.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    type("Username", "nova");
    type("Password", GOOD);
    fireEvent.click(button("Create account"));
    await screen.findByRole("heading", { name: "Save your recovery code" });
    expect(progress()).toEqual([
      { text: "Name and password (done)", current: false },
      { text: "Recovery code", current: true },
      { text: "Your first day", current: false },
    ]);
    fireEvent.click(button("I've saved my code"));
    await screen.findByText(/Today's photo is hidden/);
    expect(progress()).toBeNull();
  });

  it("shows the recovery code one time before the app", async () => {
    let meReads = 0;
    const base = signedOut();
    await openSignUp(
      signedOut({
        ...base,
        getMe: () => {
          meReads += 1;
          return base.getMe();
        },
      }),
    );
    type("Username", "nova");
    type("Password", GOOD);
    const readsBefore = meReads;
    fireEvent.click(button("Create account"));

    expect(
      await screen.findByRole("heading", { name: "Save your recovery code" }),
    ).toBeDefined();
    const code = screen.getByTestId("recovery-code").textContent ?? "";
    expect(code).toMatch(/^[A-Z2-9]{24}$/);
    expect(screen.getByText("You won't see it again.")).toBeDefined();
    // The account exists and the cookie is set, but the app waits:
    // nothing reads me again, and nothing replaces the code.
    expect(meReads).toBe(readsBefore);
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByLabelText("Username")).toBeNull();

    fireEvent.click(button("I've saved my code"));
    expect(await screen.findByText(/Today's photo is hidden/)).toBeDefined();
    expect(await screen.findByText(/, nova$/)).toBeDefined();
    // The code is gone with the step.
    expect(screen.queryByTestId("recovery-code")).toBeNull();
    expect(document.body.textContent).not.toContain(code.slice(0, 8));
  });

  it("says why a sign-up was refused", async () => {
    const cases: Array<[ApiError, RegExp]> = [
      [new ApiError(409, "name-taken"), /taken, or it looks too much like/],
      [new ApiError(400, "name-reserved"), /reserved/],
      [new ApiError(400, "name-rule"), /doesn't fit the rules/],
      [new ApiError(400, "password-usual"), /one many people use/],
      [new ApiError(400, "password-rule"), /12 to 128 characters/],
      [new ApiError(429, "too-many-attempts"), /Wait a few minutes/],
    ];
    for (const [error, expected] of cases) {
      const view = renderAt(
        "/",
        signedOut({ signUp: () => Promise.reject(error) }),
      );
      fireEvent.click(
        await view.findByRole("button", { name: "Create an account" }),
      );
      type("Username", "nova");
      type("Password", GOOD);
      fireEvent.click(button("Create account"));
      expect((await view.findByRole("alert")).textContent).toMatch(expected);
      // No account, thus no recovery code and no app.
      expect(view.queryByTestId("recovery-code")).toBeNull();
      view.unmount();
    }
  });

  it("refuses a claimed name through the mock, with the folded shape", async () => {
    await openSignUp(signedOut());
    // a-d-e folds to ade, which the mock's first player holds.
    type("Username", "a-d-e");
    type("Password", GOOD);
    fireEvent.click(button("Create account"));
    expect((await screen.findByRole("alert")).textContent).toMatch(/taken/);
  });
});

describe("get back in with the recovery code (spec A2 §3.3)", () => {
  it("trades the code for a new password and shows the new code", async () => {
    const api = signedOut();
    const made = await api.signUp("nova", GOOD, true);
    await api.signOut();
    renderAt("/", api);
    fireEvent.click(await screen.findByRole("button", { name: "Forgot it?" }));
    await screen.findByRole("heading", {
      name: "Get back in with your recovery code",
    });
    expect(button("Set a new password").disabled).toBe(true);
    // The new password has the helper line of a sign-up password.
    expect(helper("New password")).toEqual({
      text: WORD_SUMMARY,
      state: "neutral",
    });
    // A recovery is not a sign-up: no parts to show.
    expect(progress()).toBeNull();
    type("Username", "nova");
    // Small letters and spaces: capitals and hyphens do not count.
    type(
      "Recovery code",
      made.recovery_code.toLowerCase().replaceAll("-", " "),
    );
    const word = type("New password", "five slow north harbors");
    expect(word.autocomplete).toBe("new-password");
    expect(button("Set a new password").disabled).toBe(false);
    fireEvent.click(button("Set a new password"));

    expect(
      await screen.findByRole("heading", { name: "Save your recovery code" }),
    ).toBeDefined();
    const next = screen.getByTestId("recovery-code").textContent ?? "";
    expect(next).toMatch(/^[A-Z2-9]{24}$/);
    expect(next).not.toBe(made.recovery_code.replaceAll("-", ""));
    expect(screen.getByText(/had before has stopped working/)).toBeDefined();
    expect(progress()).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    fireEvent.click(button("I've saved my code"));
    expect(await screen.findByText(/, nova$/)).toBeDefined();
  });

  it("waits for a code of the right shape", async () => {
    renderAt("/", signedOut());
    fireEvent.click(await screen.findByRole("button", { name: "Forgot it?" }));
    type("Username", "nova");
    type("New password", "five slow north harbors");
    type("Recovery code", "ABCD-EFGH");
    expect(button("Set a new password").disabled).toBe(true);
    type("Recovery code", "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2");
    expect(button("Set a new password").disabled).toBe(false);
  });

  it("gives one message for each recovery that does not work", async () => {
    renderAt("/", signedOut());
    fireEvent.click(await screen.findByRole("button", { name: "Forgot it?" }));
    type("Username", "ade");
    type("Recovery code", "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2");
    type("New password", "five slow north harbors");
    fireEvent.click(button("Set a new password"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(
      /Check the username and the recovery code/,
    );
    // The player with no code learns where one comes from.
    expect(screen.getByText(/Ask the operator for one/)).toBeDefined();
    expect(screen.queryByTestId("recovery-code")).toBeNull();
  });

  it("keeps the typed username between the forms and drops the password", async () => {
    renderAt("/", signedOut());
    await screen.findByRole("heading", { name: "Sign in" });
    type("Username", "nova");
    type("Password", "something typed");
    fireEvent.click(button("Forgot it?"));
    expect((screen.getByLabelText("Username") as HTMLInputElement).value).toBe(
      "nova",
    );
    fireEvent.click(button("Back to sign in"));
    await waitFor(() =>
      expect(
        (screen.getByLabelText("Password") as HTMLInputElement).value,
      ).toBe(""),
    );
  });
});

describe("the notice on the sign-up card (spec R1 §3.1)", () => {
  async function openSignUp(api: Api): Promise<void> {
    renderAt("/", api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Create an account" }),
    );
    await screen.findByRole("heading", { name: "Create an account" });
  }

  it("holds the ruled text, version 1", () => {
    expect(NOTICE_VERSION).toBe(1);
    expect(`${NOTICE_LEAD} ${NOTICE_BODY}`).toBe(
      "Your results are public. Your username, score, words and sketches " +
        "are published in an open database after each day closes. Do not " +
        "type anything private.",
    );
  });

  it("shows the notice above the control that makes the account", async () => {
    await openSignUp(signedOut());
    const lead = screen.getByText(NOTICE_LEAD);
    expect(lead.tagName).toBe("STRONG");
    const note = lead.closest('[role="note"]') as HTMLElement;
    // The ruled text and no more: the card does not shorten it.
    expect(note.textContent).toBe(`${NOTICE_LEAD} ${NOTICE_BODY}`);
    expect(note.className).toContain("notice-warn");
    // No box to tick: the click is the agreement, and the card says so.
    const agreement = screen.getByText(
      "By creating an account, you agree to this.",
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    // In the form of the username facts, and before its one control.
    const facts = screen
      .getByText(/Everyone sees this name/)
      .closest('[role="note"]') as HTMLElement;
    expect(note.closest("form")).toBe(facts.closest("form"));
    expect(agreement.closest("form")).toBe(note.closest("form"));
    const make = button("Create account");
    expect(make.form).toBe(note.closest("form"));
    expect(
      note.compareDocumentPosition(make) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
    // A screen reader hears the notice and the agreement at the control.
    expect(make.getAttribute("aria-describedby")).toBe(
      `${note.id} ${agreement.id}`,
    );
    expect(note.id).not.toBe("");
    expect(agreement.id).not.toBe("");
  });

  it("sends the agreement with the sign-up", async () => {
    const sent: Array<[string, string, boolean]> = [];
    const base = signedOut();
    await openSignUp(
      signedOut({
        ...base,
        signUp: (username, password, agreesPublic) => {
          sent.push([username, password, agreesPublic]);
          return base.signUp(username, password, agreesPublic);
        },
      }),
    );
    type("Username", "nova");
    type("Password", GOOD);
    fireEvent.click(button("Create account"));
    await screen.findByRole("heading", { name: "Save your recovery code" });
    expect(sent).toEqual([["nova", GOOD, true]]);
  });

  it("sends the proof of the check with the sign-up", async () => {
    // Spec PW1 §4.3: the mock world has no server to sign a challenge,
    // so the form shows no widget and sends the fixed payload.
    const sent: Array<string | undefined> = [];
    const base = signedOut();
    await openSignUp(
      signedOut({
        ...base,
        signUp: (username, password, agreesPublic, proof) => {
          sent.push(proof);
          return base.signUp(username, password, agreesPublic, proof);
        },
      }),
    );
    expect(document.querySelector("altcha-widget")).toBeNull();
    type("Username", "nova");
    type("Password", GOOD);
    fireEvent.click(button("Create account"));
    await screen.findByRole("heading", { name: "Save your recovery code" });
    expect(sent).toEqual([MOCK_PROOF]);
  });

  it("starts a new check when the server refuses the proof", async () => {
    let tries = 0;
    const base = signedOut();
    await openSignUp(
      signedOut({
        ...base,
        signUp: (username, password, agreesPublic, proof) => {
          tries += 1;
          return tries === 1
            ? Promise.reject(new ApiError(400, "proof"))
            : base.signUp(username, password, agreesPublic, proof);
        },
      }),
    );
    type("Username", "nova");
    type("Password", GOOD);
    fireEvent.click(button("Create account"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/check that you're a person/);
    // The new check is done at once in the mock world, so the control
    // works again.
    await waitFor(() => expect(button("Create account").disabled).toBe(false));
    fireEvent.click(button("Create account"));
    await screen.findByRole("heading", { name: "Save your recovery code" });
    expect(tries).toBe(2);
  });

  it("makes no account from a page with an earlier notice version", async () => {
    let signUps = 0;
    const base = signedOut();
    renderAt(
      "/",
      signedOut({
        ...base,
        getSignup: () =>
          Promise.resolve({ open: true, notice_version: NOTICE_VERSION + 1 }),
        signUp: (username, password, agreesPublic) => {
          signUps += 1;
          return base.signUp(username, password, agreesPublic);
        },
      }),
    );
    expect(
      await screen.findByText(/out of date, so it can't make an account/),
    ).toBeDefined();
    expect(button("Reload")).toBeDefined();
    expect(
      screen.queryByRole("button", { name: "Create an account" }),
    ).toBeNull();
    expect(screen.queryByText(NOTICE_LEAD)).toBeNull();
    expect(signUps).toBe(0);
    // Sign-in and recovery do not agree to a notice, thus they stay.
    expect(button("Sign in")).toBeDefined();
    expect(button("Forgot it?")).toBeDefined();
  });

  it("says so when the server refuses a sign-up for the notice", async () => {
    await openSignUp(
      signedOut({
        signUp: () => Promise.reject(new ApiError(400, "notice")),
      }),
    );
    type("Username", "nova");
    type("Password", GOOD);
    fireEvent.click(button("Create account"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/agreement that your results are public/);
    expect(alert.textContent).not.toMatch(/Something went wrong/);
    expect(screen.queryByTestId("recovery-code")).toBeNull();
  });
});
