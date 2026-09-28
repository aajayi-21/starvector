/**
 * The code-based route tree (spec W1 §4: no file routing, no
 * codegen): the screens under one shell. createAppRouter takes an
 * optional history so tests run on memory history.
 *
 * "/" is the home screen and "/today" the drawing screen (spec BR1
 * §6). A signed-out browser gets the landing page on each path.
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
import { AccountScreen } from "./screens/account";
import { HistoryScreen } from "./screens/history";
import { HomeScreen } from "./screens/home";
import { HowItWorksScreen } from "./screens/how";
import { LeaderboardScreen } from "./screens/leaderboard";
import { PracticeScreen } from "./screens/practice";
import { RevealScreen } from "./screens/reveal";
import { TodayScreen } from "./screens/today";
import { WelcomeScreen } from "./screens/welcome";
import { InstallHint } from "./ui/install-hint";
import { SeasonNote, TabBar, TopBar } from "./ui/nav";
import { OfflineBanner } from "./ui/offline-banner";

function Shell(): React.JSX.Element {
  const api = useApi();
  // The key the top bar reads, thus react-query serves one request
  // for the two of them and the check costs no round trip.
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  // 401 exactly (spec M1 §9). isUnauthorized carries that rule.
  if (isUnauthorized(me.error)) {
    return <WelcomeScreen />;
  }
  return (
    <>
      <TopBar />
      <SeasonNote />
      <OfflineBanner />
      <InstallHint />
      <main className="page">
        <Outlet />
      </main>
      <TabBar />
    </>
  );
}

const rootRoute = createRootRoute({ component: Shell });

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomeScreen,
});

const todayRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/today",
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

const accountRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/account",
  component: AccountScreen,
});

const howRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/how",
  component: HowItWorksScreen,
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
  homeRoute,
  todayRoute,
  practiceRoute,
  historyRoute,
  leaderboardRoute,
  accountRoute,
  howRoute,
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
