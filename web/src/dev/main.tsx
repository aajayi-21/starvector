import "@fontsource-variable/red-hat-display/wght.css";
import "@fontsource-variable/red-hat-text/wght.css";
import "@fontsource-variable/red-hat-mono/wght.css";
import "../theme.css";
import "../app.css";
import "./dev.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { DevApp } from "./app";

const root = document.getElementById("dev-root");
if (root === null) {
  throw new Error("dev.html has no #dev-root element");
}
createRoot(root).render(
  <StrictMode>
    <DevApp />
  </StrictMode>,
);
