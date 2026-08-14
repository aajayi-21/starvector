import process from "node:process";

import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";

const proxyTarget = process.env.VITE_PROXY_TARGET ?? "http://127.0.0.1:8000";
const proxy = {
  "/api": { target: proxyTarget },
  "/image": { target: proxyTarget },
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
        navigateFallback: "index.html",
        navigateFallbackDenylist: [
          /^\/api\//,
          /^\/image\//,
          /^\/dev/,
          /^\/ui\//,
        ],
        runtimeCaching: [],
      },
    }),
  ],
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
