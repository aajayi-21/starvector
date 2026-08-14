/** Builds the app's Api from the VITE_API mode (spec W1 §2 ruling 4). */

import type { Api, ApiMode } from "./client";
import { composeApi } from "./client";
import { makeMockApi } from "./mock";
import { makeRealApi } from "./real";

export function makeApi(): Api {
  const mode: ApiMode =
    import.meta.env.VITE_API === "mock" ? "mock" : "composite";
  return composeApi(makeRealApi(), makeMockApi(), mode);
}
