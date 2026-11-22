/**
 * The code-based route tree (spec W1 §4: no file routing, no
 * codegen): the screens under one shell. createAppRouter takes an
 * optional history so tests run on memory history.
 *
 * "/" is the home screen and "/today" the drawing screen (spec BR1
 * §6). A signed-out browser gets the gate screen on each path (spec
 * A2 §3), and a player who must agree to the notice gets the notice
 * screen on each path (spec R1 §3). The two public paths are the one
 * exception (spec F1 §3): the About page and the Releases page hold
 * fixed text alone, and each browser can open them.
 */

import { useQuery } from "@tanstack/react-query";
import {
  createRootRoute,
  createRoute,
  createRouter,
  Link,
  Outlet,
  type RouterHistory,
  useRouterState,
} from "@tanstack/react-router";

import { useApi } from "./api/client";
import { isUnauthorized } from "./api/types";
import { AboutScreen } from "./screens/about";
import { AccountScreen } from "./screens/account";
import { HistoryScreen } from "./screens/history";
import { HomeScreen } from "./screens/home";
import { HowItWorksScreen } from "./screens/how";
import { LeaderboardScreen } from "./screens/leaderboard";
import { NoticeScreen, needsAgreement } from "./screens/notice";
import { PracticeScreen } from "./screens/practice";
import { ReleasesScreen } from "./screens/releases";
import { RevealScreen } from "./screens/reveal";
import { SendsScreen } from "./screens/sends";
import { TodayScreen } from "./screens/today";
import { WelcomeScreen } from "./screens/welcome";
import { SiteFooter } from "./ui/footer";
import { InstallHint } from "./ui/install-hint";
import { LogoMark } from "./ui/logo";
import { TabBar, TopBar } from "./ui/nav";
import { OfflineBanner } from "./ui/offline-banner";
import { OperatorCodeNotice } from "./ui/operator-code-notice";
import { BLEED_PATHS, NO_FOOTER_PATHS, PUBLIC_PATHS } from "./ui/site-links";

/**
 * The chrome of a public path for a browser that is not in the app: a
 * signed-out one, one that must agree to the notice, and one that
 * waits for its first answer (spec F1 §3). The brand goes home, where
 * the gate or the notice stands.
 */
function PublicShell(props: { signedOut: boolean }): React.JSX.Element {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Starvector home">
          <LogoMark />
          Starvector
        </Link>
        {props.signedOut ? (
          <div className="topbar-end">
            <Link to="/">Sign in</Link>
          </div>
        ) : null}
      </header>
      <main className="page page-has-footer">
        <Outlet />
      </main>
      <SiteFooter />
    </>
  );
}

function Shell(): React.JSX.Element {
  const api = useApi();
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  // The key the top bar reads, thus react-query serves one request
  // for the two of them and the check costs no round trip.
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.getMe() });
  // 401 exactly (spec M1 §9). isUnauthorized carries that rule.
  const signedOut = isUnauthorized(me.error);
  const mustAgree = me.data !== undefined && needsAgreement(me.data.notice);
  // A public path does not wait for me and does not read it: the page
  // is the same for each browser (spec F1 §3).
  if (PUBLIC_PATHS.has(pathname) && (signedOut || mustAgree || me.isPending)) {
    return <PublicShell signedOut={signedOut} />;
  }
  if (signedOut) {
    return <WelcomeScreen />;
  }
  // No send before the agreement (spec R1 §3.3): the notice screen
  // takes the place of the app, the drawing screen with it.
  if (mustAgree && me.data !== undefined) {
    return <NoticeScreen notice={me.data.notice} />;
  }
  const footer = !NO_FOOTER_PATHS.has(pathname);
  const pageClass = [
    "page",
    footer ? "page-has-footer" : "",
    BLEED_PATHS.has(pathname) ? "page-bleed" : "",
  ]
    .filter((name) => name !== "")
    .join(" ");
  return (
    <>
      <TopBar />
      {/* On each screen, thus no signed-in device misses it (spec A2
          §6.1). */}
      <OperatorCodeNotice />
      <OfflineBanner />
      <InstallHint />
      <main className={pageClass}>
        {/* No screen before me answers: a player who must agree to
            the notice does not get the drawing screen for a moment,
            and no start is sent for that player (spec R1 §4). */}
        {me.isPending ? (
          <p className="subtle" aria-busy="true">
            Loading…
          </p>
        ) : (
          <Outlet />
        )}
      </main>
      {footer ? <SiteFooter tabBar /> : null}
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

/** The day that practice replays; with none, the screen picks one. */
interface PracticeSearch {
  day?: string;
}

const practiceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/practice",
  component: PracticeScreen,
  validateSearch: (search: Record<string, unknown>): PracticeSearch => {
    return typeof search.day === "string" ? { day: search.day } : {};
  },
});

const historyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/history",
  component: HistoryScreen,
});

/** The part of the leaderboard, and the revealed day of its day board. */
export interface LeaderboardSearch {
  day?: string;
  board?: "skill";
}

const leaderboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/leaderboard",
  component: LeaderboardScreen,
  validateSearch: (search: Record<string, unknown>): LeaderboardSearch => ({
    ...(typeof search.day === "string" ? { day: search.day } : {}),
    ...(search.board === "skill" ? { board: "skill" } : {}),
  }),
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

const aboutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/about",
  component: AboutScreen,
});

const releasesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/releases",
  component: ReleasesScreen,
});

export interface RevealSearch {
  day?: string;
}

/** The sketches of one day (spec SS1 §7.3). No day: the latest one. */
export interface SendsSearch {
  day?: string;
}

const sendsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/sends",
  component: SendsScreen,
  validateSearch: (search: Record<string, unknown>): SendsSearch => {
    return typeof search.day === "string" ? { day: search.day } : {};
  },
});

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
  sendsRoute,
  aboutRoute,
  releasesRoute,
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
