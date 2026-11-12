import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { BackendProvider, tauriBridge } from "./lib/backend";
import "./index.css";

const root = createRoot(document.getElementById("root")!);
void tauriBridge().then((bridge) =>
  root.render(
    <StrictMode>
      <BackendProvider bridge={bridge}>
        <App />
      </BackendProvider>
    </StrictMode>,
  ),
);
