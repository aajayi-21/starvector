import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

const here = path.dirname(fileURLToPath(import.meta.url));
const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": { target: proxyTarget },
  "/image": { target: proxyTarget },
  // The invite gate is a server path (spec M1 §4). Without this
  // entry an invite URL only works against the built app, and the
  // dev server hands it to the SPA fallback instead.
  "/join": { target: proxyTarget },
};

export default defineConfig({
  plugins: [
    react(),
    // The app-shell worker (spec W1 §8): precache the static shell,
    // no runtime caching at all — a worker with no route for /api
    // or /image never answers their fetches, and the navigation
    // fallback denylist keeps address-bar hits off index.html for
    // the server-owned paths. PWA_DISABLE=1 builds (e2e) skip the
    // worker entirely.
    VitePWA({
      disable: process.env.PWA_DISABLE !== undefined,
      registerType: "autoUpdate",
      devOptions: { enabled: false },
      includeAssets: ["favicon.svg"],
      manifest: {
        name: "Starvector",
        short_name: "Starvector",
        description: "The daily sketch trial.",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#2e3440",
        theme_color: "#2e3440",
        icons: [
          {
            src: "icons/appicon-192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "icons/appicon-512.png",
            sizes: "512x512",
            type: "image/png",
          },
          {
            src: "icons/appicon-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,woff2,png,webmanifest}"],
        // The operator console (spec S2 ruling 4) stays out of the
        // worker: not precached, not fallback-served.
        globIgnores: ["dev.html", "assets/dev-*"],
        navigateFallback: "index.html",
        navigateFallbackDenylist: [
          /^\/api\//,
          /^\/image\//,
          /^\/dev/,
          // An installed client must not answer the invite gate
          // from the precached shell: the server sets the cookie.
          /^\/join\//,
        ],
        runtimeCaching: [],
      },
    }),
  ],
  build: {
    rollupOptions: {
      input: {
        main: path.resolve(here, "index.html"),
        dev: path.resolve(here, "dev.html"),
      },
    },
  },
  server: { proxy },
  preview: { proxy },
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: "unit",
          environment: "node",
          include: ["tests/unit/**/*.test.ts"],
        },
      },
      {
        extends: true,
        test: {
          name: "component",
          environment: "jsdom",
          include: ["tests/component/**/*.test.tsx"],
          setupFiles: ["tests/component/setup.ts"],
        },
      },
    ],
  },
});
