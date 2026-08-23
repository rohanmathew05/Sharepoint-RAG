import { useCallback, useEffect, useState } from "react";
import { InteractionRequiredAuthError } from "@azure/msal-browser";
import {
  AuthenticatedTemplate,
  UnauthenticatedTemplate,
  useMsal,
} from "@azure/msal-react";
import { ChatWindow } from "./components/ChatWindow";
import { ConversationSidebar } from "./components/ConversationSidebar";
import { deleteConversation, listConversations, renameConversation } from "./api/client";
import { loginRequest } from "./authConfig";
import { clearAuthError, getLatestAuthError, subscribeAuthError } from "./authEvents";
import type { ConversationSummary } from "./types";

function AuthenticatedApp() {
  const { instance, accounts } = useMsal();
  const [sessionExpired, setSessionExpired] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);

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

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await listConversations(getToken));
    } catch {
      // Sidebar list is a convenience, not the source of truth for the
      // active conversation — a failed refresh just leaves the list
      // stale until the next successful one, rather than blocking chat.
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refreshConversations();
  }, [refreshConversations]);

  async function handleDeleteConversation(id: string) {
    await deleteConversation(id, getToken);
    if (id === currentConversationId) setCurrentConversationId(null);
    await refreshConversations();
  }

  async function handleRenameConversation(id: string, title: string) {
    // Update local state immediately rather than waiting on a full
    // refetch — renaming is the one action where the round-trip delay
    // would otherwise be visible as the typed title flashing back to
    // the old one for a moment.
    setConversations((prev) => prev.map((c) => (c.id === id ? { ...c, title } : c)));
    try {
      await renameConversation(id, title, getToken);
    } catch {
      await refreshConversations(); // roll back to the real state on failure
    }
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <main className="flex flex-1 overflow-hidden">
        <ConversationSidebar
          conversations={conversations}
          activeId={currentConversationId}
          onSelect={setCurrentConversationId}
          onNew={() => setCurrentConversationId(null)}
          onDelete={handleDeleteConversation}
          onRename={handleRenameConversation}
          userName={accounts[0]?.name}
          userEmail={accounts[0]?.username}
          onSignOut={() => instance.logoutRedirect()}
        />
        <div className="flex-1 overflow-hidden">
          <ChatWindow
            getToken={getToken}
            onSessionExpired={() => setSessionExpired(true)}
            conversationId={currentConversationId}
            onConversationCreated={(id) => {
              setCurrentConversationId(id);
              refreshConversations();
            }}
            onConversationUpdated={refreshConversations}
          />
        </div>
      </main>
      {sessionExpired && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="max-w-sm rounded-lg bg-surface p-7 text-center shadow-xl">
            <h2 className="m-0 mb-2 text-lg font-semibold text-foreground">Session expired</h2>
            <p className="m-0 mb-5 text-sm text-muted-foreground">
              Your session has ended. Please sign in again to keep chatting.
            </p>
            <button
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
              onClick={() => instance.loginRedirect({ ...loginRequest, account: accounts[0] })}
            >
              Sign in with Microsoft
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function LoginScreen() {
  const { instance } = useMsal();
  // getLatestAuthError() picks up a failure that already happened before
  // this component mounted (e.g. during the redirect-back bootstrap in
  // main.tsx) — see authEvents.ts for why that matters.
  const [authError, setAuthError] = useState<string | null>(getLatestAuthError());

  useEffect(() => subscribeAuthError(setAuthError), []);

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 bg-background text-center">
      <h1 className="m-0 text-xl font-semibold text-foreground">SharePoint AI Assistant</h1>
      <p className="m-0 text-sm text-muted-foreground">
        Sign in with your Microsoft work account to get started.
      </p>
      {authError && (
        <p className="m-0 max-w-md rounded-md bg-destructive/10 px-4 py-3 text-sm leading-relaxed text-destructive">
          Sign-in failed: {authError}
          <br />
          Common causes: admin consent not granted for the app's exposed
          API scope, or the redirect URI is registered under "Web"
          instead of "Single-page application" in Entra ID.
        </p>
      )}
      <button
        className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
        onClick={() => {
          clearAuthError();
          instance.loginRedirect(loginRequest);
        }}
      >
        Sign in with Microsoft
      </button>
    </div>
  );
}

export default function App() {
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
