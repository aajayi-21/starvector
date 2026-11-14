/**
 * The share control of one result: it makes an image of the result on
 * this device and gives it to the share sheet, or saves it where the
 * browser cannot share a file.
 *
 * The image holds what the results screen shows the player, and the
 * player's own sketch. The control is on a revealed day alone, because
 * a result exists after the reveal alone.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useApi } from "../api/client";
import type { HistoryView, MeView, StoredSubmission } from "../api/types";
import { shareCard } from "../share/card";
import type { CardStroke } from "../share/draw";
import { deliverShareImage, renderShareImage } from "../share/share";
import { formatShortDay } from "./format";

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

  const label = `Share the result of ${formatShortDay(props.day)} as an image`;
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
