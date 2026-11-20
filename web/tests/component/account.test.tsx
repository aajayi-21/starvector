import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { MOCK_PASSWORD, makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

describe("the Account screen (spec A1 §3, spec BR1 §4)", () => {
  it("is reached from the avatar in the top bar", async () => {
    renderAt("/");
    fireEvent.click(await screen.findByLabelText("Your account"));
    expect(await screen.findByText("About you")).toBeDefined();
    expect(await screen.findByText("Your account")).toBeDefined();
  });

  it("shows the username and the empty account", async () => {
    renderAt("/account");
    // The username is the one name (spec A2 ruling 3): no second
    // label, no player id line, and nothing that edits a name.
    expect(await screen.findByRole("heading", { name: "ade" })).toBeDefined();
    expect(screen.getByText(/Your username\./).textContent).toMatch(
      /on the leaderboard/,
    );
    expect(screen.queryByText(/Player id/)).toBeNull();
    expect(screen.queryByLabelText(/display name/i)).toBeNull();
    const editor = (await screen.findByRole("textbox", {
      name: "About you",
    })) as HTMLTextAreaElement;
    expect(editor.value).toBe("");
    // No picture, no remove control.
    expect(screen.queryByText("Remove picture")).toBeNull();
  });

  it("saves the description through putAccount", async () => {
    const sent: string[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      putAccount: (text) => {
        sent.push(text);
        return mock.putAccount(text);
      },
    };
    renderAt("/account", api);
    const editor = await screen.findByRole("textbox", { name: "About you" });
    const save = screen.getByText("Save") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(editor, { target: { value: "I sketch coastlines." } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await screen.findByText("Saved");
    expect(sent).toEqual(["I sketch coastlines."]);
  });

  it("resyncs the draft when the stored description moves", async () => {
    // The server canonicalizes, and a second tab can save behind
    // this one — the editor must follow the stored value rather
    // than silently overwrite it with a stale draft.
    let stored = "";
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      getMe: async () => ({ ...(await mock.getMe()), description: stored }),
      putAccount: (text) => {
        stored = text.toUpperCase();
        return Promise.resolve({ description: stored });
      },
    };
    renderAt("/account", api);
    const editor = (await screen.findByRole("textbox", {
      name: "About you",
    })) as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: "hello" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(editor.value).toBe("HELLO"));
  });

  it("shows the stored picture and removes it", async () => {
    const removed: number[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      getMe: async () => ({
        ...(await mock.getMe()),
        avatar_hash: "a".repeat(64),
      }),
      deleteAvatar: () => {
        removed.push(1);
        return mock.deleteAvatar();
      },
    };
    const view = renderAt("/account", api);
    await screen.findByText("Your account");
    // The 88 px circle renders the picture, not the initials.
    expect(view.container.querySelector('img[width="88"]')).not.toBeNull();
    fireEvent.click(await screen.findByText("Remove picture"));
    await waitFor(() => expect(removed).toHaveLength(1));
  });
});

/** The button waits for the device list, then adds a device. */
async function clickAddDevice(): Promise<void> {
  const add = (await screen.findByRole("button", {
    name: "Add a device",
  })) as HTMLButtonElement;
  await waitFor(() => expect(add.disabled).toBe(false));
  fireEvent.click(add);
}

describe("devices and sign-out (spec BR1 §4)", () => {
  it("lists the devices with this one marked", async () => {
    renderAt("/account");
    const card = (await screen.findByText("Devices")).closest(
      "section",
    ) as HTMLElement;
    expect(await within(card).findByText("Chrome on Mac")).toBeDefined();
    expect(within(card).getByText("This device")).toBeDefined();
    expect(within(card).getByText("Safari on iPhone")).toBeDefined();
    // One sign-out control for each other device, none for this one.
    expect(
      within(card).getAllByRole("button", { name: "Sign out" }),
    ).toHaveLength(1);
  });

  it("shows a one-time code for a new device", async () => {
    renderAt("/account");
    await clickAddDevice();
    expect(await screen.findByText(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/)).toBeDefined();
    expect(screen.getByText(/works once and expires in/)).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Get a new code" }),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(screen.queryByText(/works once and expires in/)).toBeNull(),
    );
  });

  it("says a new device is signed in when it shows up", async () => {
    const mock = makeMockApi({ today: HARNESS_TODAY });
    let joined = false;
    const api: Api = {
      ...mock,
      getSessions: async () => {
        const base = await mock.getSessions();
        return joined
          ? {
              sessions: [
                ...base.sessions,
                {
                  id: "f".repeat(64),
                  label: "Chrome on Android",
                  created_at: `${HARNESS_TODAY}T10:00:00+00:00`,
                  current: false,
                },
              ],
            }
          : base;
      },
    };
    const view = renderAt("/account", api);
    await clickAddDevice();
    await screen.findByText(/works once and expires in/);
    joined = true;
    // The list is read again every four seconds while a code is up.
    await waitFor(
      () =>
        expect(view.getByText("Chrome on Android is signed in.")).toBeDefined(),
      { timeout: 6000 },
    );
    expect(screen.queryByText(/works once and expires in/)).toBeNull();
  }, 10_000);

  it("signs the other devices out", async () => {
    const calls: string[] = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      signOutOthers: () => {
        calls.push("others");
        return mock.signOutOthers();
      },
    };
    renderAt("/account", api);
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Sign out of all other devices",
      }),
    );
    await waitFor(() => expect(calls).toEqual(["others"]));
    await waitFor(() =>
      expect(screen.queryByText("Safari on iPhone")).toBeNull(),
    );
  });

  it("signs this device out and lands on the sign-in page", async () => {
    let signedIn = true;
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      getMe: () =>
        signedIn
          ? mock.getMe()
          : Promise.reject(new ApiError(401, undefined, "unauthorized")),
      signOut: () => {
        signedIn = false;
        return Promise.resolve({ signed_out: true });
      },
    };
    renderAt("/account", api);
    fireEvent.click(
      await screen.findByRole("button", { name: "Sign out of this device" }),
    );
    expect(
      await screen.findByText("A new hidden photo every day."),
    ).toBeDefined();
  });

  it("says so on a server with no accounts", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getSessions: () => Promise.resolve({ sessions: [] }),
    };
    renderAt("/account", api);
    expect(await screen.findByText(/runs without sign-in/)).toBeDefined();
    expect(screen.queryByText("Sign out of this device")).toBeNull();
    expect(screen.queryByRole("button", { name: "Add a device" })).toBeNull();
    // The download needs no account: it stays, alone in its row.
    const download = screen.getByRole("link", { name: "Download my data" });
    const card = download.closest("section") as HTMLElement;
    expect(within(card).getByRole("heading").textContent).toBe("Your data");
    expect(within(card).queryAllByRole("button")).toHaveLength(0);
  });

  it("offers the data download", async () => {
    renderAt("/account");
    const link = (await screen.findByRole("link", {
      name: "Download my data",
    })) as HTMLAnchorElement;
    expect(link.hasAttribute("download")).toBe(true);
    // The sentence beside the button says what the file holds.
    const hint = document.getElementById(
      link.getAttribute("aria-describedby") ?? "",
    );
    expect(hint?.textContent).toMatch(/^Every sketch and set of words/);
  });

  it("ends with one row of three moves, the deletion last", async () => {
    renderAt("/account");
    const signOut = await screen.findByRole("button", {
      name: "Sign out of this device",
    });
    const card = signOut.closest("section") as HTMLElement;
    expect(within(card).getByRole("heading").textContent).toBe(
      "Your data and account",
    );
    const moves = Array.from(card.querySelectorAll("a, button")).map((move) =>
      move.textContent?.trim(),
    );
    expect(moves).toEqual([
      "Download my data",
      "Sign out of this device",
      "Delete account",
    ]);
    // The download and the sign-out are quiet buttons with an edge. The
    // deletion is red words with no edge: it opens a section, and the
    // section holds the one filled red button.
    const download = within(card).getByRole("link", {
      name: "Download my data",
    });
    expect(download.className).toContain("btn-secondary");
    expect(signOut.className).toContain("btn-secondary");
    const opener = within(card).getByRole("button", { name: "Delete account" });
    expect(opener.className).toBe("account-delete-link");
    // No section comes after it until the deletion section opens.
    expect(card.nextElementSibling).toBeNull();
  });
});

describe("Public data (spec R1 §3.1)", () => {
  function section(): HTMLElement {
    return screen
      .getByRole("heading", { name: "Public data" })
      .closest("section") as HTMLElement;
  }

  it("says the facts the short notice does not say", async () => {
    renderAt("/account");
    await screen.findByRole("heading", { name: "Public data" });
    const facts = within(section())
      .getAllByRole("listitem")
      .map((item) => item.textContent?.replaceAll(/\s+/g, " "));
    expect(facts).toEqual([
      "The database holds your username, every score, the words you typed, and every sketch.",
      "Anyone can download it and study it.",
      "A published snapshot stays published, with your username in it, even after your account is gone.",
    ]);
  });

  it("says no snapshot is published when the server names no address", async () => {
    renderAt("/account");
    await screen.findByRole("heading", { name: "Public data" });
    expect(
      await within(section()).findByText("No snapshot is published yet."),
    ).toBeDefined();
    expect(within(section()).queryByRole("link")).toBeNull();
  });

  it("links the address of the published snapshots", async () => {
    const address = "https://data.example/starvector";
    renderAt(
      "/account",
      makeMockApi({ today: HARNESS_TODAY, publicDataUrl: address }),
    );
    await screen.findByRole("heading", { name: "Public data" });
    const link = (await within(section()).findByRole("link", {
      name: "Get the public database",
    })) as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe(address);
    // A different site: a new tab, with no way back to this one.
    expect(link.target).toBe("_blank");
    expect(link.rel).toContain("noopener");
    expect(
      within(section()).queryByText("No snapshot is published yet."),
    ).toBeNull();
  });

  it("keeps the facts when the address read fails", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getAbout: () => Promise.reject(new ApiError(0)),
    };
    renderAt("/account", api);
    await screen.findByRole("heading", { name: "Public data" });
    expect(within(section()).getAllByRole("listitem")).toHaveLength(3);
    expect((await within(section()).findByRole("alert")).textContent).toMatch(
      /Can't reach Starvector/,
    );
    expect(
      within(section()).queryByText("No snapshot is published yet."),
    ).toBeNull();
  });
});

const GOOD = "four quiet amber lanterns";

function typeInto(label: string, value: string): HTMLInputElement {
  const field = screen.getByLabelText(label) as HTMLInputElement;
  fireEvent.change(field, { target: { value } });
  return field;
}

describe("the password and the recovery code (spec A2 §3.4)", () => {
  it("changes the password with the current one and a new one", async () => {
    const sent: Array<[string, string | undefined]> = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      setPassword: (password, current) => {
        sent.push([password, current]);
        return mock.setPassword(password, current);
      },
    };
    renderAt("/account", api);
    const submit = (await screen.findByRole("button", {
      name: "Change password",
    })) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    const current = typeInto("Current password", MOCK_PASSWORD);
    const next = typeInto("New password", GOOD);
    expect(current.autocomplete).toBe("current-password");
    expect(next.autocomplete).toBe("new-password");
    expect(current.form).toBe(next.form);
    // A password manager finds the account by the form's username.
    const name = current.form?.querySelector(
      'input[autocomplete="username"]',
    ) as HTMLInputElement;
    expect(name.value).toBe("ade");
    expect(name.getAttribute("aria-hidden")).toBe("true");
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    expect(
      await screen.findByText(
        "Your password is changed. 1 other device was signed out.",
      ),
    ).toBeDefined();
    expect(sent).toEqual([[GOOD, MOCK_PASSWORD]]);
    // A change shows no recovery code: the code does not move.
    expect(screen.queryByTestId("recovery-code")).toBeNull();
    // The other device left the table.
    await waitFor(() =>
      expect(screen.queryByText("Safari on iPhone")).toBeNull(),
    );
    expect(current.value).toBe("");
    expect(next.value).toBe("");
  });

  it("shows the new-password rules while the player types", async () => {
    renderAt("/account");
    await screen.findByRole("button", { name: "Change password" });
    typeInto("Current password", MOCK_PASSWORD);
    // The username is ade, and the password must not hold it.
    typeInto("New password", "made of jade and stone");
    // One helper line: it names the broken rule, and no other.
    const line = document.getElementById(
      "account-password-rules",
    ) as HTMLElement;
    expect(line.textContent).toContain("Don't include your username");
    expect(line.className).toContain("rule-hint-broken");
    expect(
      (
        screen.getByRole("button", {
          name: "Change password",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    typeInto("New password", GOOD);
    expect(line.className).toContain("rule-hint-met");
    expect(line.className).not.toContain("rule-hint-broken");
  });

  it("says a wrong current password is wrong", async () => {
    renderAt("/account");
    await screen.findByRole("button", { name: "Change password" });
    typeInto("Current password", "not the password");
    typeInto("New password", GOOD);
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "That isn't your current password.",
    );
  });

  it("says why a new password was refused, and to wait on a 429", async () => {
    const cases: Array<[ApiError, RegExp]> = [
      [new ApiError(400, "password-usual"), /one many people use/],
      [new ApiError(400, "password-rule"), /12 to 128 characters/],
      [new ApiError(429, "too-many-attempts"), /Wait a few minutes/],
    ];
    for (const [error, expected] of cases) {
      const api: Api = {
        ...makeMockApi({ today: HARNESS_TODAY }),
        setPassword: () => Promise.reject(error),
      };
      const view = renderAt("/account", api);
      await view.findByRole("button", { name: "Change password" });
      typeInto("Current password", MOCK_PASSWORD);
      typeInto("New password", GOOD);
      fireEvent.click(view.getByRole("button", { name: "Change password" }));
      expect((await view.findByRole("alert")).textContent).toMatch(expected);
      view.unmount();
    }
  });

  it("sets a first password with no current one and shows the first code", async () => {
    const sent: Array<[string, string | undefined]> = [];
    const mock = makeMockApi({ today: HARNESS_TODAY, hasPassword: false });
    const api: Api = {
      ...mock,
      setPassword: (password, current) => {
        sent.push([password, current]);
        return mock.setPassword(password, current);
      },
    };
    renderAt("/account", api);
    // The section keeps one name, and the button says the move.
    expect(
      await screen.findByRole("button", { name: "Set a password" }),
    ).toBeDefined();
    expect(screen.getByRole("heading", { name: "Password" })).toBeDefined();
    expect(
      screen.getByText(/has no password yet\. Set one, and/),
    ).toBeDefined();
    // No current password is asked, and no code can be made yet.
    expect(screen.queryByLabelText("Current password")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "New recovery code" }),
    ).toBeNull();
    typeInto("New password", GOOD);
    fireEvent.click(screen.getByRole("button", { name: "Set a password" }));

    expect(
      await screen.findByRole("heading", { name: "Save your recovery code" }),
    ).toBeDefined();
    expect(screen.getByTestId("recovery-code").textContent).toMatch(
      /^[A-Z2-9]{24}$/,
    );
    expect(sent).toEqual([[GOOD, undefined]]);
    // The code stays through the me read that follows the change.
    expect(
      await screen.findByRole("button", { name: "New recovery code" }),
    ).toBeDefined();
    expect(screen.getByTestId("recovery-code")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "I've saved my code" }));
    expect(
      await screen.findByRole("button", { name: "Change password" }),
    ).toBeDefined();
    expect(screen.queryByTestId("recovery-code")).toBeNull();
    expect(
      screen.getByText("Your password is set. 1 other device was signed out."),
    ).toBeDefined();
  });

  it("warns a player with no password before a sign-out", async () => {
    renderAt(
      "/account",
      makeMockApi({ today: HARNESS_TODAY, hasPassword: false }),
    );
    expect(
      await screen.findByText(/Set one before you sign out/),
    ).toBeDefined();
  });

  it("makes a new recovery code for the current password", async () => {
    renderAt("/account");
    const make = (await screen.findByRole("button", {
      name: "New recovery code",
    })) as HTMLButtonElement;
    expect(make.disabled).toBe(true);
    const current = typeInto(
      "Current password, to make a new code",
      MOCK_PASSWORD,
    );
    expect(current.autocomplete).toBe("current-password");
    fireEvent.click(make);
    expect(
      await screen.findByRole("heading", { name: "Save your recovery code" }),
    ).toBeDefined();
    expect(screen.getByTestId("recovery-code").textContent).toMatch(
      /^[A-Z2-9]{24}$/,
    );
    // The earlier code is dead, and the step says so.
    expect(screen.getByText(/had before has stopped working/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "I've saved my code" }));
    await waitFor(() =>
      expect(screen.queryByTestId("recovery-code")).toBeNull(),
    );
    expect(
      screen.getByRole("button", { name: "New recovery code" }),
    ).toBeDefined();
  });

  it("refuses a new recovery code for a wrong password", async () => {
    renderAt("/account");
    await screen.findByRole("button", { name: "New recovery code" });
    typeInto("Current password, to make a new code", "not the password");
    fireEvent.click(screen.getByRole("button", { name: "New recovery code" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "That isn't your current password.",
    );
    expect(screen.queryByTestId("recovery-code")).toBeNull();
  });

  it("offers no password control on a server with no accounts", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getSessions: () => Promise.resolve({ sessions: [] }),
    };
    renderAt("/account", api);
    await screen.findByText(/runs without sign-in/);
    expect(
      screen.queryByRole("button", { name: "Change password" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "New recovery code" }),
    ).toBeNull();
  });

  it("says how to sign back in, with no invite", async () => {
    renderAt("/account");
    expect(
      await screen.findByText(/you'll need your username and password/),
    ).toBeDefined();
    expect(screen.queryByText(/invite/i)).toBeNull();
  });
});

describe("Delete my account (spec MD1 §4.3)", () => {
  /**
   * The password field of the deletion, by its id: the `Password`
   * section of the page has the same name as the field's label.
   */
  function deletePassword(): HTMLInputElement {
    return document.getElementById("delete-password") as HTMLInputElement;
  }

  function typePassword(value: string): HTMLInputElement {
    const field = deletePassword();
    fireEvent.change(field, { target: { value } });
    return field;
  }

  function deleteRow(): HTMLButtonElement {
    return screen.getByRole("button", {
      name: "Delete account",
    }) as HTMLButtonElement;
  }

  function deleteButton(): HTMLButtonElement {
    return screen.getByRole("button", {
      name: "Delete my account",
    }) as HTMLButtonElement;
  }

  /** The row waits for the device list, then opens the section. */
  async function openSection(): Promise<HTMLElement> {
    fireEvent.click(
      await screen.findByRole("button", { name: "Delete account" }),
    );
    const heading = await screen.findByRole("heading", {
      name: "Delete my account",
    });
    return heading.closest("section") as HTMLElement;
  }

  function items(card: HTMLElement, name: string): Array<string | undefined> {
    return within(within(card).getByRole("list", { name }))
      .getAllByRole("listitem")
      .map((item) => item.textContent?.replaceAll(/\s+/g, " ").trim());
  }

  it("stays closed until the row opens it, and takes the focus then", async () => {
    renderAt("/account");
    const row = await screen.findByRole("button", { name: "Delete account" });
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(
      screen.queryByRole("heading", { name: "Delete my account" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Delete my account" }),
    ).toBeNull();
    expect(document.getElementById("delete-username")).toBeNull();

    fireEvent.click(row);
    const heading = await screen.findByRole("heading", {
      name: "Delete my account",
    });
    expect(row.getAttribute("aria-expanded")).toBe("true");
    const card = heading.closest("section") as HTMLElement;
    expect(row.getAttribute("aria-controls")).toBe(card.id);
    expect(document.activeElement).toBe(heading);
    // The section is the last thing on the page, after the last row.
    expect(card.previousElementSibling).toBe(row.closest("section"));
    expect(card.nextElementSibling).toBeNull();

    // The row closes it again.
    fireEvent.click(row);
    expect(row.getAttribute("aria-expanded")).toBe("false");
    expect(
      screen.queryByRole("heading", { name: "Delete my account" }),
    ).toBeNull();
  });

  it("says what goes and what stays, and that a snapshot keeps the name", async () => {
    renderAt("/account");
    const card = await openSection();
    expect(within(card).getByText("This can't be reversed.")).toBeDefined();
    expect(items(card, "Removed for good")).toEqual([
      "Your account and sign-in",
      "Your picture and description",
      "Your password and recovery code",
      "Every signed-in device",
    ]);
    expect(items(card, "Stays public")).toEqual([
      "Your past sketches, words, and results, under an anonymous name with no picture",
      "Your username in any snapshot already published",
      "The name ade stays closed: nobody can register it again, you included",
    ]);
  });

  it("offers the data download before the deletion", async () => {
    renderAt("/account");
    const card = await openSection();
    const first = within(card).getByRole("link", {
      name: "Download my data first",
    }) as HTMLAnchorElement;
    const row = screen.getByRole("link", {
      name: "Download my data",
    }) as HTMLAnchorElement;
    expect(first.hasAttribute("download")).toBe(true);
    expect(first.getAttribute("href")).toBe(row.getAttribute("href"));
  });

  it("keeps the account, closes the section, and goes back to the row", async () => {
    let calls = 0;
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      deleteAccount: (username, password) => {
        calls += 1;
        return mock.deleteAccount(username, password);
      },
    };
    renderAt("/account", api);
    await openSection();
    typeInto("Type ade to confirm", "ade");
    typePassword(MOCK_PASSWORD);
    fireEvent.click(screen.getByRole("button", { name: "Keep my account" }));
    expect(
      screen.queryByRole("heading", { name: "Delete my account" }),
    ).toBeNull();
    expect(deleteRow().getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(deleteRow());
    expect(calls).toBe(0);
    // The typed username and password went with the section.
    await openSection();
    expect(
      (screen.getByLabelText("Type ade to confirm") as HTMLInputElement).value,
    ).toBe("");
    expect(deletePassword().value).toBe("");
    expect(deleteButton().disabled).toBe(true);
  });

  it("stays off until the typed username agrees, then deletes", async () => {
    const sent: Array<[string, string]> = [];
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      deleteAccount: (username, password) => {
        sent.push([username, password]);
        return mock.deleteAccount(username, password);
      },
    };
    renderAt("/account", api);
    await openSection();
    expect(deleteButton().disabled).toBe(true);
    // The ids stay: the browser specs and a password manager find them.
    const password = typePassword(MOCK_PASSWORD);
    expect(password.labels?.[0]?.textContent).toBe("Password");
    expect(typeInto("Type ade to confirm", "Ade").id).toBe("delete-username");
    expect(deleteButton().disabled).toBe(true);
    typeInto("Type ade to confirm", "ade");
    expect(deleteButton().disabled).toBe(false);
    expect(deleteButton().className).toContain("btn-danger-solid");
    fireEvent.click(deleteButton());
    expect(
      await screen.findByText(
        /Your account is deleted\. Your earlier results show as anon-/,
      ),
    ).toBeDefined();
    expect(sent).toEqual([["ade", MOCK_PASSWORD]]);
    // The section and its row are gone: there is no account to delete.
    expect(
      screen.queryByRole("heading", { name: "Delete my account" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete account" })).toBeNull();
    expect(screen.getByRole("button", { name: "Done" })).toBeDefined();
    // The name stays closed after the deletion.
    await expect(
      mock.signUp("ade", "a different long password", true),
    ).rejects.toMatchObject({ refusalCause: "name-taken" });
  });

  it("says a wrong password is wrong and deletes nothing", async () => {
    let calls = 0;
    const mock = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...mock,
      deleteAccount: (username, password) => {
        calls += 1;
        return mock.deleteAccount(username, password);
      },
    };
    renderAt("/account", api);
    const card = await openSection();
    typeInto("Type ade to confirm", "ade");
    typePassword("not the password");
    fireEvent.click(deleteButton());
    expect((await within(card).findByRole("alert")).textContent).toBe(
      "That isn't your current password.",
    );
    expect(calls).toBe(1);
    expect(screen.queryByText(/Your account is deleted/)).toBeNull();
    // The section stays open for a second try.
    expect(deleteRow().getAttribute("aria-expanded")).toBe("true");
  });

  it("asks an account with no password to set one first", async () => {
    renderAt(
      "/account",
      makeMockApi({ today: HARNESS_TODAY, hasPassword: false }),
    );
    const card = await openSection();
    expect(within(card).getByText(/Set a password first/).textContent).toMatch(
      /send the operator a message/,
    );
    expect(
      within(card).queryByRole("button", { name: "Delete my account" }),
    ).toBeNull();
    expect(document.getElementById("delete-username")).toBeNull();
    // The one move left closes the section.
    fireEvent.click(
      within(card).getByRole("button", { name: "Keep my account" }),
    );
    expect(
      screen.queryByRole("heading", { name: "Delete my account" }),
    ).toBeNull();
  });

  it("offers no deletion on a server with no accounts", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      getSessions: () => Promise.resolve({ sessions: [] }),
    };
    renderAt("/account", api);
    await screen.findByText(/runs without sign-in/);
    expect(screen.queryByRole("button", { name: "Delete account" })).toBeNull();
    expect(
      screen.queryByRole("heading", { name: "Delete my account" }),
    ).toBeNull();
  });
});
