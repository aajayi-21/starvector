/**
 * The console's shared controls (spec BR1 §7.6).
 *
 * The confirmation lives in the page. A browser can stop a native
 * `window.confirm` from showing, and a stopped dialog answers "no"
 * with no sign — the button then looks broken. Refusals show in a red
 * box with the server's own words, and long moves show that they are
 * working.
 */

import { useEffect, useRef, useState } from "react";

import { DevApiError, OLDER_SERVER } from "./api";

export function messageOf(error: unknown): string {
  return error instanceof DevApiError ? error.message : "refused";
}

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
    ? "not found: start the server with --dev, or the operator " +
        "token is missing or wrong"
    : messageOf(error);
}

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

export function StatusBadge(props: { status: string }): React.JSX.Element {
  return (
    <span className={`badge ${STATUS_BADGE[props.status] ?? ""}`}>
      {props.status}
    </span>
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
