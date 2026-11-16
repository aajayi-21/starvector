import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Api } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import type { PulseFacts } from "../../src/api/types";
import { ApiError } from "../../src/api/types";
import { HARNESS_TODAY, renderAt } from "./harness";

const FACTS: PulseFacts = {
  protocol: "vp1",
  pool_root: "a".repeat(64),
  pool_count: 1000,
  beacon_chain: "drand-quicknet",
  beacon_chain_hash: "c".repeat(64),
  beacon_round: 28832419,
  round_time: "2026-08-15T00:01:00Z",
};

/** The mock with a vp1 day, a vp1 reveal, and a vp1 server. */
function vp1Api(): Api {
  const base = makeMockApi({ today: HARNESS_TODAY });
  return {
    ...base,
    getAbout: async () => ({
      ...(await base.getAbout()),
      pick_protocol: "vp1",
    }),
    getDay: async () => ({
      ...(await base.getDay()),
      ...FACTS,
      commitment: null,
    }),
    getReveal: async (day?: string) => ({
      ...(await base.getReveal(day)),
      ...FACTS,
      protocol: "vp1",
      secret: null,
      commitment: null,
      check: "uv run python tools/check_day.py --reveal reveal.json",
      beacon_signature: "b".repeat(96),
      randomness: "d".repeat(64),
      target_index: 417,
      target_salt: "e".repeat(64),
      target_proof: [`R:${"f".repeat(64)}`],
    }),
  };
}

describe("the pick after the close (spec VP1 §8)", () => {
  it("says the home photo is picked after the close", async () => {
    renderAt("/", vp1Api());
    expect(
      await screen.findByText("Today's photo is picked after the close"),
    ).toBeDefined();
    expect(screen.queryByText(/hidden behind this code/)).toBeNull();
  });

  it("says so on the today screen", async () => {
    renderAt("/today", vp1Api());
    expect(
      await screen.findByText(/picked when the session closes/),
    ).toBeDefined();
  });

  it("explains the beacon on the how-it-works screen", async () => {
    renderAt("/how", vp1Api());
    expect(
      await screen.findByText(/a public random number picks the photo/),
    ).toBeDefined();
    expect(screen.getByText(/drand public randomness beacon/)).toBeDefined();
    expect(screen.queryByText(/fingerprint of the hidden/)).toBeNull();
  });

  it("says no photo is hidden on the landing page", async () => {
    const api: Api = {
      ...vp1Api(),
      getMe: () => Promise.reject(new ApiError(401, undefined, "no")),
      getDoor: () => Promise.reject(new ApiError(404, undefined, "no")),
    };
    renderAt("/history", api);
    expect(await screen.findByText("A new photo every day.")).toBeDefined();
  });

  it("shows the pulse, the position, and the set, and no secret", async () => {
    renderAt("/reveal", vp1Api());
    fireEvent.click(await screen.findByText("Check that this day was fair"));
    expect(screen.getByText(/pulse 28832419 of the drand/)).toBeDefined();
    expect(screen.getByText(/position 417 \(from 0\) of 1000/)).toBeDefined();
    expect(screen.getByText("a".repeat(64))).toBeDefined();
    expect(screen.getByRole("link", { name: "28832419" })).toBeDefined();
    expect(
      screen.getByRole("button", { name: "Save the check file" }),
    ).toBeDefined();
    expect(screen.queryByText("Secret")).toBeNull();
    expect(screen.queryByText(/test beacon/)).toBeNull();
  });

  it("warns when a test beacon picked the photo", async () => {
    const base = vp1Api();
    renderAt("/reveal", {
      ...base,
      getReveal: async (day?: string) => ({
        ...(await base.getReveal(day)),
        beacon_chain: "fake",
      }),
    });
    fireEvent.click(await screen.findByText("Check that this day was fair"));
    expect(screen.getByText(/test beacon, not the public one/)).toBeDefined();
  });
});
