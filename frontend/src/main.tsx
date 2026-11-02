import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "@fontsource-variable/bodoni-moda/opsz.css";
import "@fontsource-variable/bodoni-moda/opsz-italic.css";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/schibsted-grotesk";

import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
