import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { ShipyardApiClient } from "./api";
import { loadRuntimeConfig } from "./runtime";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Workbench root element is missing");
}

const renderBootstrapError = (): void => {
  root.setAttribute("role", "alert");
  root.textContent =
    "Workbench 无法加载本地运行时配置。请检查 Shipyard 服务是否已启动。";
};

const bootstrap = async (): Promise<void> => {
  try {
    const runtime = await loadRuntimeConfig();
    createRoot(root).render(
      <StrictMode>
        <App
          api={
            new ShipyardApiClient({
              apiBaseUrl: runtime.apiBaseUrl,
              identity: runtime.identity,
            })
          }
        />
      </StrictMode>,
    );
  } catch {
    renderBootstrapError();
  }
};

void bootstrap();
