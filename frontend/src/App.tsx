import { useState } from "react";
import { InteractionRequiredAuthError } from "@azure/msal-browser";
import {
  AuthenticatedTemplate,
  UnauthenticatedTemplate,
  useMsal,
} from "@azure/msal-react";
import { ChatWindow } from "./components/ChatWindow";
import { UserSwitcher } from "./components/UserSwitcher";
import { loginRequest, DEMO_MODE } from "./authConfig";

function DemoApp() {
  const [demoUserId, setDemoUserId] = useState("user-a");

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>AI Assistant</h1>
        <div className="header-right">
          <span className="demo-badge">Demo mode</span>
          <UserSwitcher currentUserId={demoUserId} onChange={setDemoUserId} />
        </div>
      </header>
      <main className="app-main">
        <ChatWindow getToken={async () => "demo-token"} demoUserId={demoUserId} />
      </main>
    </div>
  );
}

function AuthenticatedApp() {
  const { instance, accounts } = useMsal();

  async function getToken(): Promise<string> {
    const account = accounts[0];
    try {
      const result = await instance.acquireTokenSilent({ ...loginRequest, account });
      return result.accessToken;
    } catch (err) {
      // MSAL's own refresh token has also expired (or conditional access
      // requires fresh interaction) — the OBO exchange the backend would
      // do with a stale token is guaranteed to fail, so redirect to sign
      // in again now instead of letting the request fail server-side.
      if (err instanceof InteractionRequiredAuthError) {
        await instance.acquireTokenRedirect({ ...loginRequest, account });
      }
      throw err;
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>AI Assistant</h1>
        <div className="header-right">
          <span className="user-name">{accounts[0]?.name}</span>
          <button className="signout-btn" onClick={() => instance.logoutRedirect()}>
            Sign out
          </button>
        </div>
      </header>
      <main className="app-main">
        <ChatWindow getToken={getToken} />
      </main>
    </div>
  );
}

function LoginScreen() {
  const { instance } = useMsal();
  return (
    <div className="login-screen">
      <h1>SharePoint AI Assistant</h1>
      <p>Sign in with your Microsoft work account to get started.</p>
      <button className="login-btn" onClick={() => instance.loginRedirect(loginRequest)}>
        Sign in with Microsoft
      </button>
    </div>
  );
}

export default function App() {
  if (DEMO_MODE) {
    return <DemoApp />;
  }

  return (
    <>
      <AuthenticatedTemplate>
        <AuthenticatedApp />
      </AuthenticatedTemplate>
      <UnauthenticatedTemplate>
        <LoginScreen />
      </UnauthenticatedTemplate>
    </>
  );
}
