import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "../../tokens.css";
import "./page-header.css";
import "./surface-system.css";
import "./specialized-workspaces.css";
import "./plan-import.css";
import "./analytics-report.css";
import "./companion-slot.css";
import "./anna-conversation.css";
import "./styles.css";
import "./studyforge.css";
import "./direction-contract.css";
import "./home-workstation.css";
import "./log-journal.css";
import "./top-toolbar.css";
import "./workstation-system.css";

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js");
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
