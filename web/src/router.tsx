/**
 * The code-based route tree (spec W1 §4: no file routing, no
 * codegen): four screens under one shell. createAppRouter takes an
 * optional history so tests run on memory history.
 */

import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from "@tanstack/react-router";

import { HistoryScreen } from "./screens/history";
import { PracticeScreen } from "./screens/practice";
import { RevealScreen } from "./screens/reveal";
import { TodayScreen } from "./screens/today";
import { Nav } from "./ui/nav";
import { OfflineBanner } from "./ui/offline-banner";

function Shell(): React.JSX.Element {
  return (
    <>
      <OfflineBanner />
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
