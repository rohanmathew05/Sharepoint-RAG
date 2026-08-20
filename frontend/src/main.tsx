import React from "react";
import ReactDOM from "react-dom/client";
import { EventType, PublicClientApplication } from "@azure/msal-browser";
import type { EventMessage } from "@azure/msal-browser";
import { MsalProvider } from "@azure/msal-react";
import App from "./App";
import { msalConfig, DEMO_MODE } from "./authConfig";
import { recordAuthError } from "./authEvents";
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

  // Registered before initialize()/handleRedirectPromise() run, so a
  // failure processed during that bootstrap (e.g. right after the
  // redirect back from Entra ID) can't be missed — see authEvents.ts.
  msalInstance.addEventCallback((event: EventMessage) => {
    if (event.eventType === EventType.LOGIN_FAILURE || event.eventType === EventType.ACQUIRE_TOKEN_FAILURE) {
      recordAuthError(event.error?.message ?? "Sign-in failed for an unknown reason.");
    }
  });

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
