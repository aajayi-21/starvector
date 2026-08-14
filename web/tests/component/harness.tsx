/**
 * The component-test harness: full-mock Api, a fresh query client,
 * and the real route tree on memory history.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import type { Api } from "../../src/api/client";
import { ApiContext } from "../../src/api/client";
import { makeMockApi } from "../../src/api/mock";
import { createAppRouter } from "../../src/router";

export const HARNESS_TODAY = "2026-08-14";

export function renderAt(path: string, api?: Api) {
  const wired = api ?? makeMockApi({ today: HARNESS_TODAY });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createAppRouter(
    createMemoryHistory({ initialEntries: [path] }),
  );
  return render(
    <ApiContext.Provider value={wired}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ApiContext.Provider>,
  );
}
