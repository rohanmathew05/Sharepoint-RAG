/**
 * A tiny store for MSAL login/token failures, populated from
 * main.tsx as soon as the PublicClientApplication is created — before
 * initialize()/handleRedirectPromise() run, and before any React
 * component mounts.
 *
 * This exists because subscribing to MSAL's events from inside a React
 * component (e.g. a useEffect in LoginScreen) is too late: the redirect
 * response is processed as part of MsalProvider's own bootstrap, which
 * can complete — and fire LOGIN_FAILURE — before that component's effect
 * has run. A failure in that gap was being silently dropped, leaving the
 * user bounced back to the login screen with no visible error at all.
 */
type Listener = (message: string | null) => void;

let latestError: string | null = null;
const listeners = new Set<Listener>();

export function recordAuthError(message: string): void {
  latestError = message;
  listeners.forEach((listener) => listener(message));
}

export function clearAuthError(): void {
  latestError = null;
  listeners.forEach((listener) => listener(null));
}

export function getLatestAuthError(): string | null {
  return latestError;
}

export function subscribeAuthError(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
