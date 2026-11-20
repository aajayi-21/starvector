import "@fontsource-variable/red-hat-display/wght.css";
import "@fontsource-variable/red-hat-text/wght.css";
import "@fontsource-variable/red-hat-mono/wght.css";
import "@fontsource/newsreader/400-italic.css";
import "./theme.css";
import "./app.css";
import "./styles/home.css";
import "./styles/play.css";
import "./styles/results.css";
import "./styles/board.css";
import "./styles/account.css";
import "./styles/gate.css";
import "./styles/pages.css";

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
