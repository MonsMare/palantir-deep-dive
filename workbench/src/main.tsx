import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ShipyardApiClient } from "./api";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Workbench root element is missing");
}

createRoot(root).render(
  <StrictMode>
    <App api={new ShipyardApiClient()} />
  </StrictMode>,
);
