import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://127.0.0.1:4173" },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // The square canvas is ~830 px tall on desktop — the viewport
        // must hold it fully or mouse strokes land outside the page.
        viewport: { width: 1440, height: 1200 },
      },
    },
  ],
  webServer: [
    {
      command: "uv run python web/e2e/serve_fixture.py",
      cwd: repoRoot,
      port: 8199,
      timeout: 240_000,
      reuseExistingServer: false,
      stdout: "ignore",
      stderr: "pipe",
    },
    {
      command:
        "pnpm run build:e2e && pnpm exec vite preview --port 4173 --strictPort",
      port: 4173,
      timeout: 240_000,
      // Never adopt a foreign server: a manually started preview is a
      // PWA-enabled build proxying at the REAL dev server on :8000.
      reuseExistingServer: false,
      env: { VITE_PROXY_TARGET: "http://127.0.0.1:8199" },
    },
  ],
});
