/**
 * The stages of one stored day, for the track of the Days tab.
 *
 * The stages follow the protocol of the day (spec VP1 §3.3 and §6). A
 * commit-v1 day picks its target at the open, thus it has three
 * stages. A vp1 day picks its target in the close, after the blind
 * run of spec CR1 §4, thus it has a pick stage between the close and
 * the reveal.
 *
 * Each function here is pure: the day record in, the stages out.
 */

import type { PickProtocol } from "../api/types";
import type { DevDayStatus } from "./types";

/**
 * The protocol of a stored day, read from its record.
 *
 * The dev wire sends no protocol field. Spec VP1 §6 fixes the rule
 * that this reads: a vp1 day holds no commitment at all, and a
 * commit-v1 day holds one from the open.
 */
export function dayProtocol(commitment: string | null): PickProtocol {
  return commitment === null || commitment === "" ? "vp1" : "commit-v1";
}

/** A vp1 day has a target only after the close records the pick. */
export function isPicked(targetId: string | null): boolean {
  return targetId !== null && targetId !== "";
}

export type StageId = "opened" | "close" | "pick" | "reveal";

/** "current" is the stage that the next move of the day completes. */
export type StageState = "done" | "current" | "pending";

export interface DayStage {
  id: StageId;
  label: string;
  state: StageState;
}

/**
 * The stages of a day, in sequence, each with its state.
 *
 * `picked` says if the record holds a target. A close that stopped
 * part way can leave a vp1 day in `closing` with the pick recorded,
 * and the pick stage then shows as done while the close stays
 * current.
 */
export function dayStages(
  protocol: PickProtocol,
  status: DevDayStatus,
  picked: boolean,
): DayStage[] {
  const closed = status === "closed" || status === "revealed";
  const stages: DayStage[] = [
    { id: "opened", label: "Opened", state: "done" },
    {
      id: "close",
      label: "Close and score",
      state: closed ? "done" : "current",
    },
  ];
  if (protocol === "vp1") {
    stages.push({
      id: "pick",
      label: "Pick photo",
      state: picked ? "done" : "pending",
    });
  }
  stages.push({
    id: "reveal",
    label: "Reveal",
    state:
      status === "revealed"
        ? "done"
        : status === "closed"
          ? "current"
          : "pending",
  });
  return stages;
}

/** One sentence that says when this day's photo is picked. */
export function pickSentence(protocol: PickProtocol): string {
  return protocol === "vp1"
    ? "A public random number picks this day's photo after the close (protocol vp1)."
    : "This day picked its photo when it opened (protocol commit-v1).";
}
