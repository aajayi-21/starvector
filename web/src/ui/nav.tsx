/**
 * The app chrome (spec BR1 §6): a top bar with the five places, and
 * below 760 px a bottom tab bar instead, so a phone keeps one row of
 * chrome at the top and the thumb reaches the tabs. The avatar is the
 * way into the account screen (spec A1 §3).
 */

import {
  ChartBar,
  House,
  PencilSimpleLine,
  Target,
  UsersThree,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";

import { useApi } from "../api/client";
import { AvatarCircle } from "./avatar";
import { LogoMark } from "./logo";

const activeProps = { "aria-current": "page" } as const;

interface Place {
  to: "/" | "/today" | "/practice" | "/history" | "/leaderboard";
  label: string;
  short: string;
  icon: typeof House;
}

const PLACES: ReadonlyArray<Place> = [
  { to: "/", label: "Home", short: "Home", icon: House },
  { to: "/today", label: "Today", short: "Today", icon: PencilSimpleLine },
  { to: "/practice", label: "Practice", short: "Practice", icon: Target },
  { to: "/history", label: "Your results", short: "Results", icon: ChartBar },
  {
    to: "/leaderboard",
    label: "Leaderboard",
    short: "Board",
    icon: UsersThree,
  },
];

export function TopBar(): React.JSX.Element {
  const api = useApi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="Starvector home">
        <LogoMark />
        Starvector
      </Link>
      <nav className="topnav" aria-label="Main">
        {PLACES.map((place) => (
          <Link
            key={place.to}
            to={place.to}
            activeProps={activeProps}
            activeOptions={{ exact: place.to === "/" }}
          >
            {place.label}
          </Link>
        ))}
      </nav>
      <div className="topbar-end">
        {me.data === undefined || me.data.streak === 0 ? null : (
          <span className="badge badge-accent hide-narrow">
            {me.data.streak}-day streak
          </span>
        )}
        {me.data === undefined ? null : (
          <Link to="/account" className="avatar-link" aria-label="Your account">
            <AvatarCircle
              player={me.data.player}
              displayName={me.data.display_name}
              avatarHash={me.data.avatar_hash}
              size={34}
            />
          </Link>
        )}
      </div>
    </header>
  );
}

export function TabBar(): React.JSX.Element {
  return (
    <nav className="tabbar" aria-label="Main">
      {PLACES.map((place) => {
        const Icon = place.icon;
        return (
          <Link
            key={place.to}
            to={place.to}
            activeProps={activeProps}
            activeOptions={{ exact: place.to === "/" }}
          >
            <Icon size={24} aria-hidden="true" />
            {place.short}
          </Link>
        );
      })}
    </nav>
  );
}

/**
 * The test-season line (spec P1a R13): while the pool is a
 * development pool, each screen says its numbers are test numbers.
 */
export function SeasonNote(): React.JSX.Element | null {
  const api = useApi();
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  if (about.data?.test_season !== true) {
    return null;
  }
  return (
    <div className="season-note" role="note">
      Test season — results use a small practice set of {about.data.photo_count}{" "}
      photos and won't carry over to the public launch.
    </div>
  );
}
