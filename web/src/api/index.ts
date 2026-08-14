/** Builds the app's Api from the VITE_API mode (spec W1 §2 ruling 4). */

import type { Api, ApiMode } from "./client";
import { composeApi } from "./client";
import { makeMockApi } from "./mock";
import { makeRealApi } from "./real";

export function makeApi(): Api {
  const mode: ApiMode =
    import.meta.env.VITE_API === "mock" ? "mock" : "composite";
  // The mock's calendar anchors at the wall clock so day-addressed
  // surfaces line up with the live world; the fixed test anchor
  // stays a test concern.
  const today = new Date().toISOString().slice(0, 10);
  return composeApi(makeRealApi(), makeMockApi({ today }), mode);
}
