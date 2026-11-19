/**
 * The operator console (spec S2 §5, grown by spec BR1 §7): four tabs
 * over the dev unit — Days, Automatic days, Players, and Results
 * database. Reached locally or through the SSH tunnel; the proxy
 * answers 404 for it in production.
 *
 * The tabs stay mounted when hidden, so a switch loses nothing that
 * was loaded. An apply of the token — a blur of its field, Enter, or
 * the button — and a day moved from any tab make each tab read again.
 *
 * The day listing is the first operator read. When the server refuses
 * it with the constant 404, the console shows one locked card with
 * the token field and hides the tabs, which hold nothing then.
 */

import { LockKey } from "@phosphor-icons/react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import type { AboutView } from "../api/types";
import { LogoMark } from "../ui/logo";
import type { DevApi } from "./api";
import { makeDevApi } from "./api";
import type { Access } from "./controls";
import { DaysTab } from "./days-tab";
import { IndexTab } from "./index-tab";
import { PlayersTab } from "./players-tab";
import { ScheduleTab } from "./schedule-tab";
import type { DevSchedule } from "./types";

/** Where the operator token is kept between visits. */
export const TOKEN_KEY = "sv:dev:token";
/** Where the open tab is kept between visits. */
export const TAB_KEY = "sv:dev:tab";

const TABS = [
  { id: "days", label: "Days" },
  { id: "schedule", label: "Automatic days" },
  { id: "players", label: "Players" },
  { id: "index", label: "Results database" },
] as const;

type TabId = (typeof TABS)[number]["id"];

function stored(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    // A browser with storage refused still runs the console; the
    // operator pastes the token on each visit.
    return "";
  }
}

function keep(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage refused: the value still holds for this visit.
  }
}

function storedTab(): TabId {
  const value = stored(TAB_KEY);
  return TABS.find((tab) => tab.id === value)?.id ?? "days";
}

/** The two causes of the constant 404, for the locked card. */
const LOCKED_HELP =
  "The server answered “not found”. Check the token, or start the server with --dev.";

/**
 * The token field, in the locked card and in the header.
 *
 * Each keystroke stores the token, and the client reads it at call
 * time. Enter and the button apply it, and so does a blur — except a
 * blur into the form's own button, where the click applies it.
 */
function TokenForm(props: {
  token: string;
  onType: (token: string) => void;
  onApply: () => void;
  submitLabel: string;
  busy: boolean;
  /** The card shows a label above the field; the header does not. */
  labeled: boolean;
}): React.JSX.Element {
  const field = useRef<HTMLInputElement>(null);
  const id = useId();

  useEffect(() => {
    // The form shows when the operator must type: start in the field.
    field.current?.focus();
  }, []);

  return (
    <form
      className={props.labeled ? "dev-token-form" : "dev-token-inline"}
      onSubmit={(event) => {
        event.preventDefault();
        props.onApply();
      }}
    >
      {props.labeled ? (
        <label className="label" htmlFor={id}>
          Operator token
        </label>
      ) : null}
      <input
        ref={field}
        id={id}
        className="input dev-token"
        type="password"
        aria-label="operator token"
        placeholder={props.labeled ? undefined : "Operator token"}
        value={props.token}
        onChange={(event) => props.onType(event.target.value)}
        onBlur={(event) => {
          const next = event.relatedTarget;
          if (
            next instanceof Node &&
            event.currentTarget.form?.contains(next)
          ) {
            return;
          }
          props.onApply();
        }}
      />
      <button
        type="submit"
        className={
          props.labeled
            ? "btn btn-primary btn-block"
            : "btn btn-secondary dev-small-button"
        }
        disabled={props.busy}
      >
        {props.busy ? "Checking…" : props.submitLabel}
      </button>
    </form>
  );
}

/** The connection state for the header: a dot and one or two words. */
function connectionOf(access: Access | null): { dot: string; text: string } {
  if (access === null) {
    return { dot: "dev-dot-off", text: "Connecting…" };
  }
  switch (access.state) {
    case "connected":
      return { dot: "dev-dot-on", text: "Connected" };
    case "locked":
      return { dot: "dev-dot-warn", text: "Locked" };
    case "failed":
      return { dot: "dev-dot-off", text: "Not connected" };
  }
}

export function DevApp(props: { api?: DevApi }): React.JSX.Element {
  const [token, setToken] = useState(() => stored(TOKEN_KEY));
  // Read at call time, so a pasted token takes effect on the next
  // request. Held in a ref so the client is built once.
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const [api] = useState<DevApi>(
    () => props.api ?? makeDevApi(() => tokenRef.current),
  );
  const [tab, setTab] = useState<TabId>(storedTab);
  // Bumped when the token is applied or a tab moves a day: each tab
  // reads again.
  const [reload, setReload] = useState(0);
  const bump = useCallback(() => setReload((count) => count + 1), []);
  const [about, setAbout] = useState<AboutView | null>(null);
  // What the newest day listing said about the token. Null until the
  // first listing answers.
  const [access, setAccess] = useState<Access | null>(null);
  // An apply waits for its listing.
  const [checking, setChecking] = useState(false);
  // The operator applied a token and the server refused it again.
  const [refusedAgain, setRefusedAgain] = useState(false);
  // The header's token field shows after "Change token".
  const [editing, setEditing] = useState(false);
  const [schedule, setSchedule] = useState<DevSchedule | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const applied = useRef(false);

  useEffect(() => {
    api
      .getAbout()
      .then(setAbout)
      .catch(() => setAbout(null));
  }, [api]);

  const type = (value: string) => {
    setToken(value);
    keep(TOKEN_KEY, value);
  };

  const apply = () => {
    applied.current = true;
    setChecking(true);
    setEditing(false);
    bump();
  };

  const onAccess = useCallback((next: Access) => {
    setAccess(next);
    setChecking(false);
    setRefusedAgain(
      next.state === "locked" && applied.current && tokenRef.current !== "",
    );
    if (next.state === "connected") {
      applied.current = false;
    }
  }, []);

  const pick = (next: TabId) => {
    setTab(next);
    keep(TAB_KEY, next);
  };

  // Arrow keys move between the tabs (the WAI-ARIA tabs pattern).
  const onTabKey = (event: React.KeyboardEvent, index: number) => {
    const step =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step === 0) {
      return;
    }
    event.preventDefault();
    const nextIndex = (index + step + TABS.length) % TABS.length;
    const next = TABS[nextIndex];
    if (next !== undefined) {
      pick(next.id);
      tabRefs.current[nextIndex]?.focus();
    }
  };

  const locked = access?.state === "locked";
  const connection = connectionOf(access);

  return (
    <div className="dev-shell">
      <header className="dev-header">
        <span className="brand">
          <LogoMark />
          Starvector
        </span>
        <span className="badge badge-warn">
          Operator console · development only
        </span>
        <span className="dev-season subtle small">
          {about === null
            ? ""
            : [
                about.test_season ? "Test season" : "Live season",
                `${about.photo_count} photos`,
                about.closes_at_utc === null
                  ? "days move by hand"
                  : `days close ${about.closes_at_utc} UTC`,
              ].join(" · ")}
        </span>
        <span
          className="dev-connection small"
          role="status"
          data-testid="console-connection"
          title={access?.state === "failed" ? access.message : undefined}
        >
          <span className={`dev-dot ${connection.dot}`} aria-hidden="true" />
          {connection.text}
        </span>
        {locked ? null : editing ? (
          <TokenForm
            token={token}
            onType={type}
            onApply={apply}
            submitLabel="Apply"
            busy={false}
            labeled={false}
          />
        ) : (
          <button
            type="button"
            className="btn btn-ghost dev-small-button"
            onClick={() => setEditing(true)}
          >
            Change token
          </button>
        )}
        <a className="small" href="/">
          Player app
        </a>
      </header>

      <div
        className="dev-tabs"
        role="tablist"
        aria-label="Console sections"
        hidden={locked}
      >
        {TABS.map((item, index) => (
          <button
            key={item.id}
            ref={(element) => {
              tabRefs.current[index] = element;
            }}
            type="button"
            role="tab"
            id={`dev-tab-${item.id}`}
            aria-selected={tab === item.id}
            aria-controls={`dev-panel-${item.id}`}
            tabIndex={tab === item.id ? 0 : -1}
            className="dev-tab"
            onClick={() => pick(item.id)}
            onKeyDown={(event) => onTabKey(event, index)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <main className="dev-main">
        {locked ? (
          <section className="card dev-locked" data-testid="console-locked">
            <span className="dev-locked-icon" aria-hidden="true">
              <LockKey size={24} />
            </span>
            <h1 className="dev-h2">Enter the operator token</h1>
            {refusedAgain && !checking ? (
              <div className="notice notice-bad" role="alert">
                That token did not open the console. {LOCKED_HELP}
              </div>
            ) : (
              <p className="muted">{LOCKED_HELP}</p>
            )}
            <TokenForm
              token={token}
              onType={type}
              onApply={apply}
              submitLabel="Unlock"
              busy={checking}
              labeled={true}
            />
            <p className="hint">
              The token stays in this browser, so the next visit opens with it.
            </p>
          </section>
        ) : null}
        {/* The tabs stay mounted while the card shows: the Days tab's
            listing is the read that says when the token is accepted. */}
        <div hidden={locked}>
          <div
            role="tabpanel"
            id="dev-panel-days"
            aria-labelledby="dev-tab-days"
            hidden={tab !== "days"}
          >
            <DaysTab
              api={api}
              reload={reload}
              onChanged={bump}
              about={about}
              schedule={schedule}
              onAccess={onAccess}
            />
          </div>
          <div
            role="tabpanel"
            id="dev-panel-schedule"
            aria-labelledby="dev-tab-schedule"
            hidden={tab !== "schedule"}
          >
            <ScheduleTab
              api={api}
              reload={reload}
              onChanged={bump}
              onView={setSchedule}
            />
          </div>
          <div
            role="tabpanel"
            id="dev-panel-players"
            aria-labelledby="dev-tab-players"
            hidden={tab !== "players"}
          >
            <PlayersTab api={api} reload={reload} />
          </div>
          <div
            role="tabpanel"
            id="dev-panel-index"
            aria-labelledby="dev-tab-index"
            hidden={tab !== "index"}
          >
            <IndexTab api={api} reload={reload} />
          </div>
        </div>
      </main>
    </div>
  );
}
