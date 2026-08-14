import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function typeImpression(text: string): Promise<void> {
  const input = await screen.findByPlaceholderText(
    "one impression — Enter commits",
  );
  fireEvent.change(input, { target: { value: text } });
  fireEvent.keyDown(input, { key: "Enter" });
}

describe("the Today screen", () => {
  it("renders the open workspace with code cells and palette", async () => {
    renderAt("/");
    await screen.findByText("Send today's trial");
    const day = await makeMockApi({ today: HARNESS_TODAY }).getDay();
    for (const cell of day.trial_code) {
      expect(screen.getAllByText(cell).length).toBeGreaterThan(0);
    }
    expect(screen.getByLabelText("color ink")).toBeDefined();
    expect(screen.getByLabelText("color teal")).toBeDefined();
    expect(screen.getByText("Send today's trial")).toBeDefined();
  });

  it("disables send until something is scoreable", async () => {
    renderAt("/");
    const send = (await screen.findByText(
      "Send today's trial",
    )) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    await typeImpression("tall vertical structure");
    await waitFor(() => expect(send.disabled).toBe(false));
  });

  it("locks the button while the send is in flight", async () => {
    let release: (value: { trial_id: string; atom_count: number }) => void =
      () => undefined;
    const gate = new Promise<{ trial_id: string; atom_count: number }>(
      (resolve) => {
        release = resolve;
      },
    );
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => gate,
    };
    renderAt("/", api);
    await typeImpression("cold");
    const send = (await screen.findByText(
      "Send today's trial",
    )) as HTMLButtonElement;
    fireEvent.click(send);
    // In flight: the button is disabled — a second click cannot post.
    const sending = (await screen.findByText("Sending…")) as HTMLButtonElement;
    expect(sending.disabled).toBe(true);
    release({ trial_id: "ab".repeat(16), atom_count: 1 });
    expect(await screen.findByText(/Sent\./)).toBeDefined();
    expect(screen.getByText("ab".repeat(16))).toBeDefined();
    expect(screen.getByText(/1 atoms/)).toBeDefined();
  });

  it("fires exactly one POST for a synchronous double-click", async () => {
    let calls = 0;
    let release: (value: { trial_id: string; atom_count: number }) => void =
      () => undefined;
    const gate = new Promise<{ trial_id: string; atom_count: number }>(
      (resolve) => {
        release = resolve;
      },
    );
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => {
        calls += 1;
        return gate;
      },
    };
    renderAt("/", api);
    await typeImpression("cold");
    const send = await screen.findByText("Send today's trial");
    // isPending flips a task late — the ref guard must catch the
    // second click of the same task.
    fireEvent.click(send);
    fireEvent.click(send);
    release({ trial_id: "cd".repeat(16), atom_count: 1 });
    await screen.findByText(/Sent\./);
    expect(calls).toBe(1);
  });

  it("shows friendly copy for an already-submitted 409, not the token", async () => {
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () => Promise.reject(new ApiError(409, "already-submitted")),
    };
    renderAt("/", api);
    await typeImpression("cold");
    fireEvent.click(await screen.findByText("Send today's trial"));
    // The 409 locks the screen into the submitted view.
    expect(await screen.findByText(/Sent\./)).toBeDefined();
    expect(screen.queryByText("already-submitted")).toBeNull();
  });

  it("renders a gate refusal's own detail", async () => {
    const detail =
      "no atom reads into a weighted channel - add an impression, a " +
      "labeled group, or strokes";
    const api: Api = {
      ...makeMockApi({ today: HARNESS_TODAY }),
      submit: () =>
        Promise.reject(new ApiError(400, "no-scoreable-atom", detail)),
    };
    renderAt("/", api);
    await typeImpression("cold");
    fireEvent.click(await screen.findByText("Send today's trial"));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      detail,
    );
  });

  it("autosaves the draft to localStorage, keyed by day", async () => {
    renderAt("/");
    await typeImpression("water nearby");
    await waitFor(
      () => {
        const raw = window.localStorage.getItem(`sv:draft:${HARNESS_TODAY}`);
        expect(raw).not.toBeNull();
        expect(JSON.parse(raw as string).impressions).toEqual(["water nearby"]);
      },
      { timeout: 2000 },
    );
  });

  it("shows the submitted view when the server says submitted", async () => {
    const base = makeMockApi({ today: HARNESS_TODAY });
    const api: Api = {
      ...base,
      getDay: async () => ({ ...(await base.getDay()), submitted: true }),
    };
    renderAt("/", api);
    expect(await screen.findByText(/Sent\./)).toBeDefined();
    expect(screen.queryByText("Send today's trial")).toBeNull();
  });
});
