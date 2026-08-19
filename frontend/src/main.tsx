import React from "react";
import ReactDOM from "react-dom/client";
import { PublicClientApplication } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import App from "./App";
import { msalConfig, DEMO_MODE } from "./authConfig";
import "./styles.css";

const root = ReactDOM.createRoot(document.getElementById("root")!);

if (DEMO_MODE) {
  // No Entra ID app registration configured — skip MSAL entirely so the
  // demo runs without any Azure setup. See src/authConfig.ts.
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
} else {
  const msalInstance = new PublicClientApplication(msalConfig);
  msalInstance.initialize().then(() => {
    root.render(
      <React.StrictMode>
        <MsalProvider instance={msalInstance}>
          <App />
        </MsalProvider>
      </React.StrictMode>
    );
  });
}
