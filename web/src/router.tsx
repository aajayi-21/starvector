/**
 * The code-based route tree (spec W1 §4: no file routing, no
 * codegen): four screens under one shell. createAppRouter takes an
 * optional history so tests run on memory history.
 */

import { useQuery } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from "@tanstack/react-router";

import { useApi } from "./api/client";
import { isUnauthorized } from "./api/types";
import { HistoryScreen } from "./screens/history";
import { LeaderboardScreen } from "./screens/leaderboard";
import { PracticeScreen } from "./screens/practice";
import { RevealScreen } from "./screens/reveal";
import { TodayScreen } from "./screens/today";
import { InstallHint } from "./ui/install-hint";
import { InviteGate } from "./ui/invite-gate";
import { Nav } from "./ui/nav";
import { OfflineBanner } from "./ui/offline-banner";

function Shell(): React.JSX.Element {
  const api = useApi();
  // The key Nav reads, thus react-query serves one request for the
  // two of them and the gate costs no round trip.
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  // 401 exactly (spec M1 §9). isUnauthorized carries that rule.
  if (isUnauthorized(me.error)) {
    return <InviteGate />;
  }
  return (
    <>
      <OfflineBanner />
      <InstallHint />
      <Nav />
      <Outlet />
    </>
  );
}

const rootRoute = createRootRoute({ component: Shell });

const todayRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: TodayScreen,
});

const practiceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/practice",
  component: PracticeScreen,
});

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: HistoryScreen,
});

const leaderboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/leaderboard",
  component: LeaderboardScreen,
});

export interface RevealSearch {
  day?: string;
}

const revealRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reveal",
  component: RevealScreen,
  validateSearch: (search: Record<string, unknown>): RevealSearch => {
    return typeof search.day === "string" ? { day: search.day } : {};
  },
});

const routeTree = rootRoute.addChildren([
  todayRoute,
  practiceRoute,
  historyRoute,
  leaderboardRoute,
  revealRoute,
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    ...(history === undefined ? {} : { history }),
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
