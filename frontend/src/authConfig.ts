import type { Configuration } from "@azure/msal-browser";

// Fill these in from your Entra ID App Registration to enable real
// Microsoft sign-in. Values are safe to expose in the frontend bundle —
// they identify the app registration, they are not secrets. The client
// secret and Azure OpenAI key stay server-side only (backend/.env).
export const msalConfig: Configuration = {
  auth: {
    clientId: import.meta.env.VITE_ENTRA_CLIENT_ID ?? "",
    authority: `https://login.microsoftonline.com/${
      import.meta.env.VITE_ENTRA_TENANT_ID ?? "common"
    }`,
    redirectUri: import.meta.env.VITE_REDIRECT_URI ?? window.location.origin,
  },
  cache: {
    cacheLocation: "sessionStorage",
  },
};

// The scope the frontend requests when signing the user in. The backend
// then exchanges this token for a Graph-scoped token via the On-Behalf-Of
// flow — the frontend never talks to Graph directly.
export const loginRequest = {
  scopes: [`api://${import.meta.env.VITE_ENTRA_CLIENT_ID ?? ""}/access_as_user`],
};

// When true (default, and true whenever no Entra ID app registration is
// configured), the app skips real MSAL sign-in and instead lets the user
// pick one of two demo identities via a dropdown, matching the backend's
// DEMO_MODE fixture users. This is what makes the permission-aware
// retrieval demo runnable without an Azure tenant.
export const DEMO_MODE = !import.meta.env.VITE_ENTRA_CLIENT_ID;
