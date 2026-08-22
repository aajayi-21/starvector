import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { HARNESS_TODAY, renderAt } from "./harness";

describe("the Account screen (spec A1 §3)", () => {
  it("is reached from the nav avatar", async () => {
    renderAt("/");
    const link = await screen.findByLabelText("your account");
    fireEvent.click(link);
    expect(await screen.findByText("About you")).toBeDefined();
    expect(await screen.findByText("Your account")).toBeDefined();
  });

  it("shows the identity and the empty account", async () => {
    renderAt("/account");
    // The store key and the label render side by side; the mock's
    // label equals the key, so both hits are the same string.
    expect(await screen.findAllByText("ade")).not.toHaveLength(0);
    const editor = (await screen.findByLabelText(
      "account description",
    )) as HTMLTextAreaElement;
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
    const editor = await screen.findByLabelText("account description");
    const save = screen.getByText("Save") as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(editor, { target: { value: "I sketch coastlines." } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await screen.findByText("saved");
    expect(sent).toEqual(["I sketch coastlines."]);
  });

  it("resyncs the draft when the stored description moves", async () => {
    // The server canonicalizes, and a second tab can save behind
    // this one — the editor must follow the stored value rather
    // than silently overwrite it with a stale draft (the review
    // of 2026-08-21).
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
    const editor = (await screen.findByLabelText(
      "account description",
    )) as HTMLTextAreaElement;
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
    // The 96 px circle renders the picture, not the initials.
    expect(view.container.querySelector('img[width="96"]')).not.toBeNull();
    fireEvent.click(await screen.findByText("Remove picture"));
    await waitFor(() => expect(removed).toHaveLength(1));
  });
});
