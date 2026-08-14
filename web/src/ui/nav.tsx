/**
 * The app nav (mock screens 1a-1f): logo v2-nav (spec W1 ruling 7),
 * the four items, the streak tag, and the avatar initial. Streak
 * and player come from /api/me — mock-served until the backend
 * phase.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../api/client";
import navMark from "../brand/starvector-logo-v2-nav.svg";

const activeProps = { "aria-current": "page" } as const;

export function Nav(): React.JSX.Element {
  const api = useApi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const initial = (me.data?.player ?? "").slice(0, 2).toUpperCase();
  return (
    <nav
      className="nav"
      style={{ borderBottom: "1px solid var(--color-divider)" }}
    >
      <span
        className="nav-brand"
        style={{ display: "flex", alignItems: "center", gap: 10 }}
      >
        <img className="nav-mark" src={navMark} width={18} height={18} alt="" />
        Starvector
      </span>
      <Link to="/" activeProps={activeProps} activeOptions={{ exact: true }}>
        Today
      </Link>
      <Link to="/practice" activeProps={activeProps}>
        Practice
      </Link>
      <Link to="/history" activeProps={activeProps}>
        History
      </Link>
      <Link to="/reveal" activeProps={activeProps}>
        Leaderboard
      </Link>
      {me.data === undefined ? null : (
        <span className="tag tag-accent" style={{ whiteSpace: "nowrap" }}>
          streak&nbsp;{me.data.streak}
        </span>
      )}
      {initial === "" ? null : (
        <span
          aria-hidden="true"
          style={{
            width: 28,
            height: 28,
            borderRadius: "50%",
            background: "var(--color-neutral-800)",
            color: "var(--color-neutral-200)",
            display: "grid",
            placeItems: "center",
            fontSize: 11,
            fontWeight: 500,
          }}
        >
          {initial}
        </span>
      )}
    </nav>
  );
}
