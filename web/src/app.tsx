/**
 * The app shell (spec W1 B5): the Api provider, the query client
 * (retry off — failures surface, §8), and the router.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useState } from "react";

import { makeApi } from "./api";
import { ApiContext } from "./api/client";
import { createAppRouter } from "./router";

export function App(): React.JSX.Element {
  const [api] = useState(() => makeApi());
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, refetchOnWindowFocus: false },
        },
      }),
  );
  const [router] = useState(() => createAppRouter());
  return (
    <ApiContext.Provider value={api}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ApiContext.Provider>
  );
}
