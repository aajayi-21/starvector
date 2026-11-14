import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { MOCK_PASSWORD, makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
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

/** The rule line with these words, and if the screen marks it met. */
function rule(text: RegExp): { met: boolean } {
  const line = screen.getByText(text).closest("li") as HTMLElement;
  return { met: line.className.includes("rule-ok") };
}

describe("the gate screen (spec A2 §3)", () => {
  it("shows the three controls when the server makes accounts", async () => {
    renderAt("/", signedOut());
    expect(
      await screen.findByRole("heading", { name: "Sign in" }),
    ).toBeDefined();
    expect(button("Sign in")).toBeDefined();
    expect(
      await screen.findByRole("button", { name: "Make an account" }),
    ).toBeDefined();
    expect(button("I do not have my password")).toBeDefined();
    // The device code stays: the way in with no password to type.
    expect(screen.getByLabelText("Signed in on another device?")).toBeDefined();
    expect(screen.queryByText(/invite/i)).toBeNull();
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
      screen.queryByRole("button", { name: "Make an account" }),
    ).toBeNull();
    // Sign-in and recovery stay for each account the store holds.
    expect(button("Sign in")).toBeDefined();
    expect(button("I do not have my password")).toBeDefined();
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
      await screen.findByRole("button", { name: "Make an account" }),
    );
    fireEvent.click(button("Back to sign in"));
    fireEvent.click(button("I do not have my password"));
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
      await screen.findByRole("button", { name: "Make an account" }),
    );
    await screen.findByRole("heading", { name: "Make an account" });
  }

  it("shows the rules while the player types", async () => {
    await openSignUp(signedOut());
    // Each rule is on screen before a character is typed.
    expect(rule(/3 to 20 characters/).met).toBe(false);
    expect(rule(/letters a to z, the digits 0 to 9, and the hyphen/).met).toBe(
      false,
    );
    expect(rule(/Starts with a letter/).met).toBe(false);
    expect(rule(/No hyphen at the end/).met).toBe(false);
    expect(rule(/12 to 128 characters/).met).toBe(false);
    expect(
      screen.getByText("Not a password that many people use"),
    ).toBeDefined();
    expect(
      screen.getByText(/don't need capitals, digits, or\s+symbols/),
    ).toBeDefined();
    expect(button("Make an account").disabled).toBe(true);

    const name = type("Username", "Nova-");
    expect(name.value).toBe("nova-");
    expect(rule(/3 to 20 characters/).met).toBe(true);
    expect(rule(/Starts with a letter/).met).toBe(true);
    expect(rule(/No hyphen at the end/).met).toBe(false);
    type("Username", "nova");
    expect(rule(/No hyphen at the end/).met).toBe(true);

    // The password must not hold the username.
    type("Password", "nova nova nova nova");
    expect(rule(/12 to 128 characters/).met).toBe(true);
    expect(rule(/Does not contain your username/).met).toBe(false);
    expect(button("Make an account").disabled).toBe(true);
    type("Password", GOOD);
    expect(rule(/Does not contain your username/).met).toBe(true);
    expect(button("Make an account").disabled).toBe(false);
  });

  it("ties each rule list to its field, with the state in words", async () => {
    await openSignUp(signedOut());
    const name = screen.getByLabelText("Username");
    const rules = document.getElementById(
      name.getAttribute("aria-describedby") ?? "",
    ) as HTMLElement;
    expect(within(rules).getAllByText("(not met yet)")).toHaveLength(4);
    type("Username", "nova");
    expect(within(rules).getAllByText("(met)")).toHaveLength(4);
    const word = screen.getByLabelText("Password") as HTMLInputElement;
    expect(word.autocomplete).toBe("new-password");
    expect(
      document.getElementById(word.getAttribute("aria-describedby") ?? ""),
    ).not.toBeNull();
  });

  it("says what a username is before the account is made", async () => {
    await openSignUp(signedOut());
    // The season line is a note too: this one is in the form.
    const note = screen
      .getByText("Before you make it:")
      .closest('[role="note"]') as HTMLElement;
    expect(note.closest("form")).not.toBeNull();
    expect(note.textContent).toMatch(/shown to every\s+other player/);
    expect(note.textContent).toMatch(/can never be changed/);
    expect(note.textContent).toMatch(/Don't use your real name/);
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
    fireEvent.click(button("Make an account"));

    expect(
      await screen.findByRole("heading", { name: "Save your recovery code" }),
    ).toBeDefined();
    const code = screen.getByTestId("recovery-code").textContent ?? "";
    expect(code).toMatch(/^[A-Z2-9]{24}$/);
    expect(screen.getByText("It will not be shown again.")).toBeDefined();
    // The account exists and the cookie is set, but the app waits:
    // nothing reads me again, and nothing replaces the code.
    expect(meReads).toBe(readsBefore);
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByLabelText("Username")).toBeNull();

    fireEvent.click(button("I have my code"));
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
        await view.findByRole("button", { name: "Make an account" }),
      );
      type("Username", "nova");
      type("Password", GOOD);
      fireEvent.click(button("Make an account"));
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
    fireEvent.click(button("Make an account"));
    expect((await screen.findByRole("alert")).textContent).toMatch(/taken/);
  });
});

describe("get back in with the recovery code (spec A2 §3.3)", () => {
  it("trades the code for a new password and shows the new code", async () => {
    const api = signedOut();
    const made = await api.signUp("nova", GOOD);
    await api.signOut();
    renderAt("/", api);
    fireEvent.click(
      await screen.findByRole("button", { name: "I do not have my password" }),
    );
    await screen.findByRole("heading", {
      name: "Get back in with your recovery code",
    });
    expect(button("Set a new password").disabled).toBe(true);
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
    expect(screen.queryByRole("navigation")).toBeNull();
    fireEvent.click(button("I have my code"));
    expect(await screen.findByText(/, nova$/)).toBeDefined();
  });

  it("waits for a code of the right shape", async () => {
    renderAt("/", signedOut());
    fireEvent.click(
      await screen.findByRole("button", { name: "I do not have my password" }),
    );
    type("Username", "nova");
    type("New password", "five slow north harbors");
    type("Recovery code", "ABCD-EFGH");
    expect(button("Set a new password").disabled).toBe(true);
    type("Recovery code", "ABCD-EFGH-JKMN-PQRS-TUVW-XYZ2");
    expect(button("Set a new password").disabled).toBe(false);
  });

  it("gives one message for each recovery that does not work", async () => {
    renderAt("/", signedOut());
    fireEvent.click(
      await screen.findByRole("button", { name: "I do not have my password" }),
    );
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
    fireEvent.click(button("I do not have my password"));
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
