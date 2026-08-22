/**
 * The app nav (mock screens 1a-1f): logo v2-nav (spec W1 ruling 7),
 * the four items, the streak tag, and the avatar. The circle is the
 * way into the account screen (spec A1 §3): it links to /account
 * and shows the stored picture when the account holds one.
 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../api/client";
import navMark from "../brand/starvector-logo-v2-nav.svg";
import { AvatarCircle } from "./avatar";

const activeProps = { "aria-current": "page" } as const;

export function Nav(): React.JSX.Element {
  const api = useApi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
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
      <Link to="/leaderboard" activeProps={activeProps}>
        Leaderboard
      </Link>
      {me.data === undefined ? null : (
        <span className="tag tag-accent" style={{ whiteSpace: "nowrap" }}>
          streak&nbsp;{me.data.streak}
        </span>
      )}
      {me.data === undefined ? null : (
        <Link
          to="/account"
          aria-label="your account"
          style={{ display: "flex", padding: 0 }}
        >
          <AvatarCircle
            player={me.data.player}
            displayName={me.data.display_name}
            avatarHash={me.data.avatar_hash}
            size={28}
          />
        </Link>
      )}
    </nav>
  );
}
