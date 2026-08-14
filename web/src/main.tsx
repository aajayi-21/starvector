import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./nocturne.css";
import "./app.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app";

if (import.meta.env.PROD) {
  // The plugin serves a no-op module when the worker is disabled.
  import("virtual:pwa-register").then(({ registerSW }) =>
    registerSW({ immediate: true }),
  );
}

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element");
}
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
