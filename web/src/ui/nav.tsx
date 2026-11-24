/**
 * The app chrome (spec BR1 §6): a top bar with the four places, and
 * below 760 px a bottom tab bar instead, so a phone keeps one row of
 * chrome at the top and the thumb reaches the tabs. The avatar is the
 * way into the account screen (spec A1 §3).
 *
 * `Play` is one place with two views, the daily challenge and the instant trial. It
 * leads to today's sketch, and it is the current place on each of the
 * two paths.
 */

import {
  ChartBar,
  House,
  PencilSimpleLine,
  UsersThree,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { useState } from "react";

import { useApi } from "../api/client";
import { AvatarCircle } from "./avatar";
import { LogoMark } from "./logo";

const activeProps = { "aria-current": "page" } as const;

interface Place {
  to: "/" | "/today" | "/history" | "/leaderboard";
  label: string;
  short: string;
  icon: typeof House;
}

const PLACES: ReadonlyArray<Place> = [
  { to: "/", label: "Home", short: "Home", icon: House },
  { to: "/today", label: "Play", short: "Play", icon: PencilSimpleLine },
  { to: "/history", label: "Your results", short: "Results", icon: ChartBar },
  {
    to: "/leaderboard",
    label: "Leaderboard",
    short: "Board",
    icon: UsersThree,
  },
];

/**
 * The links of the places, for the top bar and for the tab bar. The
 * router marks a link current on its own path; Play is also current
 * on the instant path, which no link here points at.
 */
function PlaceLinks(props: { icons: boolean }): React.JSX.Element {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  return (
    <>
      {PLACES.map((place) => {
        const Icon = place.icon;
        const onInstant = place.to === "/today" && pathname === "/instant";
        return (
          <Link
            key={place.to}
            to={place.to}
            activeProps={activeProps}
            activeOptions={{ exact: place.to === "/" }}
            {...(onInstant ? activeProps : {})}
          >
            {props.icons ? <Icon size={24} aria-hidden="true" /> : null}
            {props.icons ? place.short : place.label}
          </Link>
        );
      })}
    </>
  );
}

export function TopBar(): React.JSX.Element {
  const api = useApi();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  const about = useQuery({
    queryKey: ["about"],
    queryFn: () => api.getAbout(),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const [seasonOpen, setSeasonOpen] = useState(false);
  const testSeason = about.data?.test_season === true;
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Starvector home">
          <LogoMark />
          Starvector
        </Link>
        <nav className="topnav" aria-label="Main">
          <PlaceLinks icons={false} />
        </nav>
        <div className="topbar-end">
          {/* The short sign of a test season, on each screen (spec P1a
              R13). The full sentence opens under the bar. */}
          {testSeason ? (
            <button
              type="button"
              className="badge badge-warn season-badge"
              aria-expanded={seasonOpen}
              aria-controls="season-note"
              onClick={() => setSeasonOpen((open) => !open)}
            >
              Test season
            </button>
          ) : null}
          {me.data === undefined || me.data.streak === 0 ? null : (
            <span className="badge badge-accent hide-narrow">
              {me.data.streak}-day streak
            </span>
          )}
          {me.data === undefined ? null : (
            <Link
              to="/account"
              className="avatar-link"
              aria-label="Your account"
            >
              <AvatarCircle
                player={me.data.player}
                avatarHash={me.data.avatar_hash}
                size={32}
                streak={me.data.streak}
              />
            </Link>
          )}
        </div>
      </header>
      {testSeason && seasonOpen ? (
        <div id="season-note" className="season-note" role="note">
          Results use a small practice set of {about.data?.photo_count} photos
          and won't carry over to the public launch.
        </div>
      ) : null}
    </>
  );
}

export function TabBar(): React.JSX.Element {
  return (
    <nav className="tabbar" aria-label="Main">
      <PlaceLinks icons />
    </nav>
  );
}
