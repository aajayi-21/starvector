/**
 * The console's shared controls (spec BR1 §7.6).
 *
 * The confirmation lives in the page. A browser can stop a native
 * `window.confirm` from showing, and a stopped dialog answers "no"
 * with no sign — the button then looks broken. Refusals show in a red
 * box with the server's own words, and long moves show that they are
 * working.
 *
 * The file also holds the parts that each tab builds from: the status
 * badge, the row that opens, and the reading of a refused operator
 * check.
 */

import { CaretRight } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import { DevApiError, OLDER_SERVER } from "./api";

export function messageOf(error: unknown): string {
  return error instanceof DevApiError ? error.message : "refused";
}

/** The two causes of the constant 404, in plain words. */
export const REFUSED_HELP =
  "The server answered “not found”. Check the operator token, or start " +
  "the server with --dev.";

/**
 * The wording for a refused dev read. The server answers a refused
 * operator check with the same 404 it gives with no --dev flag, on
 * purpose: a 401 there would announce that dev mode is on. The console
 * only runs against a dev server, so it can name both causes.
 */
export function refusedRead(error: unknown): string {
  if (error instanceof DevApiError && error.message === OLDER_SERVER) {
    return OLDER_SERVER;
  }
  return error instanceof DevApiError && error.status === 404
    ? REFUSED_HELP
    : messageOf(error);
}

/**
 * What the last day listing says about the operator token.
 *
 * The day listing is the first operator read of the console, thus its
 * answer decides if the console shows its tabs or the locked card.
 * "locked" is the constant 404: no token, a token that does not
 * agree, or a server with no --dev flag. "failed" is each other
 * failure, where a new token repairs nothing.
 */
export type Access =
  | { state: "connected" }
  | { state: "locked" }
  | { state: "failed"; message: string };

/** The access that a failed day listing means. */
export function accessOfFailure(error: unknown): Access {
  const refused =
    error instanceof DevApiError &&
    error.status === 404 &&
    error.message !== OLDER_SERVER;
  return refused
    ? { state: "locked" }
    : { state: "failed", message: refusedRead(error) };
}

/** Ticks each 30 s so the "in 3 h" distances stay true. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

/** The question before a ranking on an open day (spec PL1 §8). */
export const SHOWS_TARGET =
  "This day is open. The ranking shows the target, and that ends a blind run for this day. Nothing is stored.";

type Variant = "primary" | "secondary" | "danger";

/** A button that asks in place before it acts. */
export function ConfirmAction(props: {
  label: string;
  question: string;
  confirmLabel: string;
  onConfirm: () => void;
  variant?: Variant;
  disabled?: boolean;
}): React.JSX.Element {
  const variant = props.variant ?? "primary";
  const [asking, setAsking] = useState(false);
  const yes = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (asking) {
      yes.current?.focus();
    }
  }, [asking]);

  if (!asking) {
    return (
      <button
        type="button"
        className={`btn btn-${variant}`}
        disabled={props.disabled}
        onClick={() => setAsking(true)}
      >
        {props.label}
      </button>
    );
  }
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: Escape cancels; the buttons inside carry the actions
    <div
      className="dev-confirm"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setAsking(false);
        }
      }}
    >
      <p>{props.question}</p>
      <div className="dev-row dev-wrap">
        <button
          ref={yes}
          type="button"
          className={`btn btn-${variant === "danger" ? "danger-solid" : "primary"}`}
          onClick={() => {
            setAsking(false);
            props.onConfirm();
          }}
        >
          {props.confirmLabel}
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => setAsking(false)}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

const STATUS_BADGE: Record<string, string> = {
  open: "badge-good",
  active: "badge-good",
  closing: "badge-warn",
  closed: "badge-warn",
  revealed: "badge-accent",
  configured: "badge-accent",
  revoked: "badge-bad",
};

/** "open" → "Open": a wire value in sentence case, for a label. */
export function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function StatusBadge(props: { status: string }): React.JSX.Element {
  return (
    <span className={`badge ${STATUS_BADGE[props.status] ?? ""}`}>
      {sentenceCase(props.status)}
    </span>
  );
}

/**
 * A row that opens in place: the title on the left, a short meta text
 * and a chevron on the right, and the body below when it is open.
 *
 * With `open` and `onToggle` the caller holds the open flag, thus it
 * can close the row from outside. Without them the row keeps its own.
 */
export function Disclosure(props: {
  title: string;
  meta?: string;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  children: React.ReactNode;
}): React.JSX.Element {
  const { open, onToggle } = props;
  const held = open !== undefined && onToggle !== undefined;
  return (
    <details className="row-disclosure" open={held ? open : undefined}>
      {/* biome-ignore lint/a11y/noStaticElementInteractions: a summary is the native control of its details, with the keyboard built in */}
      <summary
        onClick={
          held
            ? (event) => {
                // The caller's flag is the truth: stop the browser's
                // own toggle and move the flag.
                event.preventDefault();
                onToggle(!open);
              }
            : undefined
        }
      >
        <span>{props.title}</span>
        <span className="row-meta">
          {props.meta ?? ""}
          <CaretRight className="row-chevron" size={16} aria-hidden="true" />
        </span>
      </summary>
      <div className="row-body">{props.children}</div>
    </details>
  );
}

/** The server's refusal, in a red box. Nothing when there is none. */
export function ErrorNote(props: { text: string }): React.JSX.Element | null {
  if (props.text === "") {
    return null;
  }
  return (
    <div className="notice notice-bad" role="alert">
      {props.text}
    </div>
  );
}

/** A move in progress: a spinner and what it is doing. */
export function WorkingNote(props: { text: string }): React.JSX.Element {
  return (
    <p className="dev-working" role="status">
      <span className="dev-spinner" aria-hidden="true" />
      {props.text}
    </p>
  );
}
