import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "../nocturne.css";
import "../app.css";

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
