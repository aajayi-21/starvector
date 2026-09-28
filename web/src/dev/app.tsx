/**
 * The operator console (spec S2 §5, grown by spec BR1 §7): four tabs
 * over the dev unit — Days, Automatic days, Players, and Results
 * database. Reached locally or through the SSH tunnel; the proxy
 * answers 404 for it in production.
 *
 * The tabs stay mounted when hidden, so a switch loses nothing that
 * was loaded. A blur of the token field, and a day moved from any tab,
 * make each tab read again.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { AboutView } from "../api/types";
import type { DevApi } from "./api";
import { makeDevApi } from "./api";
import { DaysTab } from "./days-tab";
import { IndexTab } from "./index-tab";
import { PlayersTab } from "./players-tab";
import { ScheduleTab } from "./schedule-tab";

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
  // Bumped when the token field blurs or a tab moves a day: each tab
  // reads again.
  const [reload, setReload] = useState(0);
  const bump = useCallback(() => setReload((count) => count + 1), []);
  const [about, setAbout] = useState<AboutView | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    api
      .getAbout()
      .then(setAbout)
      .catch(() => setAbout(null));
  }, [api]);

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

  return (
    <div className="dev-shell">
      <header className="dev-header">
        <div className="dev-brand">
          <span className="dev-brand-name">Starvector console</span>
          <span className="dev-badge">development only</span>
        </div>
        <span className="dev-season">
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
        <span style={{ flex: 1 }} />
        <a className="dev-link" href="/">
          Player app
        </a>
        <input
          className="input dev-token"
          type="password"
          aria-label="operator token"
          placeholder="operator token"
          value={token}
          onChange={(event) => {
            setToken(event.target.value);
            keep(TOKEN_KEY, event.target.value);
          }}
          onBlur={bump}
        />
      </header>

      <div className="dev-tabs" role="tablist" aria-label="Console sections">
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
        <div
          role="tabpanel"
          id="dev-panel-days"
          aria-labelledby="dev-tab-days"
          hidden={tab !== "days"}
        >
          <DaysTab api={api} reload={reload} onChanged={bump} />
        </div>
        <div
          role="tabpanel"
          id="dev-panel-schedule"
          aria-labelledby="dev-tab-schedule"
          hidden={tab !== "schedule"}
        >
          <ScheduleTab api={api} reload={reload} onChanged={bump} />
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
      </main>
    </div>
  );
}
