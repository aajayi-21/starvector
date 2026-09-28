import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

describe("the Account screen (spec A1 §3, spec BR1 §4)", () => {
  it("is reached from the avatar in the top bar", async () => {
    renderAt("/");
    fireEvent.click(await screen.findByLabelText("Your account"));
    expect(await screen.findByText("About you")).toBeDefined();
    expect(await screen.findByText("Your account")).toBeDefined();
  });

  it("shows the identity and the empty account", async () => {
    renderAt("/account");
    expect(await screen.findByText("Player id: ade")).toBeDefined();
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
  });

  it("offers the data download", async () => {
    renderAt("/account");
    const link = (await screen.findByRole("link", {
      name: "Download my data",
    })) as HTMLAnchorElement;
    expect(link.hasAttribute("download")).toBe(true);
  });
});
