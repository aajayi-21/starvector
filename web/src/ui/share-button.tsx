/**
 * The share controls: each makes an image on this device and gives it
 * to the share sheet, or saves it where the browser cannot share a
 * file.
 *
 * `ShareResultButton` is the control of one result. Its image holds
 * what the results screen shows the player, and the player's own
 * sketch. It is on a revealed day alone, because a result exists after
 * the reveal alone.
 *
 * `ShareSketchButton` is the control of the player's own sketch, after
 * the send and before the reveal (spec SS1 §6). Its image holds the
 * sketch and no result: no score, no code, and no word of the send.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import type { HistoryView, MeView, StoredSubmission } from "../api/types";
import { readSent } from "../intake/drafts";
import { shareCard, sketchCard } from "../share/card";
import type { CardStroke } from "../share/draw";
import {
  deliverShareImage,
  renderShareImage,
  renderSketchImage,
} from "../share/share";
import { useDayNames } from "./day-names";

export interface SharedTrial {
  p: number;
  target_rank: number;
  decoy_count: number;
}

type Status = "idle" | "working" | "shared" | "saved" | "failed";

const STATUS_TEXT: Record<Status, string> = {
  idle: "",
  working: "Making the image…",
  shared: "Shared.",
  saved: "Image saved.",
  failed: "Couldn't make the image. Try again.",
};

function ShareIcon(): React.JSX.Element {
  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="18" cy="5" r="3" />
      <circle cx="6" cy="12" r="3" />
      <circle cx="18" cy="19" r="3" />
      <path d="M8.6 10.5l6.8-4M8.6 13.5l6.8 4" />
    </svg>
  );
}

export function ShareResultButton(props: {
  day: string;
  trial: SharedTrial;
  /** The day's code, when the screen has it. */
  trialCode?: string | undefined;
  /** "icon" is the small control of a table row. */
  variant?: "icon" | "button";
}): React.JSX.Element {
  const api = useApi();
  const queryClient = useQueryClient();
  const names = useDayNames();
  const [status, setStatus] = useState<Status>("idle");
  const variant = props.variant ?? "button";

  async function strokesOf(): Promise<ReadonlyArray<CardStroke>> {
    try {
      const stored = await queryClient.fetchQuery<StoredSubmission>({
        queryKey: ["submission", props.day],
        queryFn: () => api.getSubmission(props.day),
        retry: false,
      });
      return stored.record.canvas_strokes;
    } catch {
      // No stored sketch: the card shows the result with no sketch.
      return [];
    }
  }

  async function playerOf(): Promise<string | null> {
    try {
      const me = await queryClient.fetchQuery<MeView>({
        queryKey: ["me"],
        queryFn: () => api.getMe(),
      });
      return me.player;
    } catch {
      return null;
    }
  }

  async function codeOf(): Promise<string | null> {
    if (props.trialCode !== undefined) {
      return props.trialCode;
    }
    try {
      const history = await queryClient.fetchQuery<HistoryView>({
        queryKey: ["history"],
        queryFn: () => api.getHistory(),
      });
      return (
        history.days.find((row) => row.day === props.day)?.trial_code ?? null
      );
    } catch {
      return null;
    }
  }

  async function share(): Promise<void> {
    setStatus("working");
    try {
      const [strokes, player, trialCode] = await Promise.all([
        strokesOf(),
        playerOf(),
        codeOf(),
      ]);
      const card = shareCard({
        day: props.day,
        dateLine: names.long(props.day),
        trialCode,
        p: props.trial.p,
        targetRank: props.trial.target_rank,
        decoyCount: props.trial.decoy_count,
        player,
        host: window.location.host,
      });
      const blob = await renderShareImage(card, strokes);
      const outcome = await deliverShareImage(blob, card);
      setStatus(outcome === "cancelled" ? "idle" : outcome);
    } catch {
      setStatus("failed");
    }
  }

  const label = `Share the result of ${names.short(props.day)} as an image`;
  return (
    <span className="share-control">
      <button
        type="button"
        className={
          variant === "icon"
            ? "btn btn-ghost btn-icon"
            : "btn btn-secondary share-button"
        }
        aria-label={label}
        title="Share as an image"
        disabled={status === "working"}
        onClick={() => void share()}
      >
        <ShareIcon />
        {variant === "button" ? <span>Share</span> : null}
      </button>
      <span
        className={
          status === "failed" ? "share-status share-status-bad" : "share-status"
        }
        role="status"
        aria-live="polite"
      >
        {STATUS_TEXT[status]}
      </span>
    </span>
  );
}

/**
 * The strokes of the caller's own send of a day, or null when there is
 * no sketch to share: the copy that this device kept at the send, else
 * the record that the server gives the caller back. The points and the
 * colors alone go on: no word and no label of the send.
 */
function useOwnSketch(day: string): ReadonlyArray<CardStroke> | null {
  const api = useApi();
  const [kept] = useState(() => readSent(day));
  const stored = useQuery<StoredSubmission>({
    queryKey: ["submission", day],
    queryFn: () => api.getSubmission(day),
    retry: false,
    enabled: kept === null,
  });
  const record = kept ?? stored.data?.record ?? null;
  if (record === null || record.canvas_strokes.length === 0) {
    return null;
  }
  return record.canvas_strokes.map(
    (stroke): CardStroke =>
      stroke.color === undefined
        ? { points: stroke.points }
        : { points: stroke.points, color: stroke.color },
  );
}

/**
 * The share control of the player's own sketch (spec SS1 §6). It shows
 * after the send, where the sketch is there to share: a send with no
 * stroke has no control.
 */
export function ShareSketchButton(props: {
  day: string;
  /** True when the photo is picked after the day closes (spec VP1). */
  postClose: boolean;
}): React.JSX.Element | null {
  const api = useApi();
  const queryClient = useQueryClient();
  const names = useDayNames();
  const [status, setStatus] = useState<Status>("idle");
  const strokes = useOwnSketch(props.day);
  if (strokes === null) {
    return null;
  }

  async function playerOf(): Promise<string | null> {
    try {
      const me = await queryClient.fetchQuery<MeView>({
        queryKey: ["me"],
        queryFn: () => api.getMe(),
      });
      return me.player;
    } catch {
      return null;
    }
  }

  async function share(sketch: ReadonlyArray<CardStroke>): Promise<void> {
    setStatus("working");
    try {
      const card = sketchCard({
        day: props.day,
        dateLine: names.long(props.day),
        player: await playerOf(),
        host: window.location.host,
        postClose: props.postClose,
      });
      const blob = await renderSketchImage(card, sketch);
      const outcome = await deliverShareImage(blob, card);
      setStatus(outcome === "cancelled" ? "idle" : outcome);
    } catch {
      setStatus("failed");
    }
  }

  return (
    <span className="share-control">
      <button
        type="button"
        className="btn btn-secondary share-button"
        aria-label="Share your sketch as an image"
        title="Share as an image"
        disabled={status === "working"}
        onClick={() => void share(strokes)}
      >
        <ShareIcon />
        <span>Share your sketch</span>
      </button>
      <span
        className={
          status === "failed" ? "share-status share-status-bad" : "share-status"
        }
        role="status"
        aria-live="polite"
      >
        {STATUS_TEXT[status]}
      </span>
    </span>
  );
}
