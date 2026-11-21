/** Builds the app's Api from the VITE_API mode (spec W1 §2 ruling 4). */

import { labelAt } from "../ui/day-calendar";
import type { Api, ApiMode } from "./client";
import { composeApi } from "./client";
import { makeMockApi } from "./mock";
import { makeRealApi } from "./real";

/** The rollover hour of the mock server: the hour of production. */
const MOCK_CLOSES_AT_UTC = "00:00";

export function makeApi(): Api {
  const mode: ApiMode =
    import.meta.env.VITE_API === "mock" ? "mock" : "composite";
  // The mock's calendar anchors at the wall clock so day-addressed
  // surfaces line up with the live world; the fixed test anchor
  // stays a test concern. The label is the one the server's calendar
  // gives at this instant, and the day view holds its close, so the
  // preview names each day as production does.
  const today = labelAt(new Date(), MOCK_CLOSES_AT_UTC);
  return composeApi(
    makeRealApi(),
    makeMockApi({
      today,
      closesAtUtc: MOCK_CLOSES_AT_UTC,
      serveClose: true,
    }),
    mode,
  );
}
