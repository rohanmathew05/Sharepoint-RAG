import type { ChatMessage, ChatResponse } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  errorCode?: string;
  constructor(message: string, errorCode?: string) {
    super(message);
    this.errorCode = errorCode;
  }
}

// Matches backend/main.py's obo_token_expired_handler — a terminal 401
// the backend raises when the user's session is genuinely gone (not
// something a silent token refresh can fix), as opposed to a plain
// network/validation error.
export class SessionExpiredError extends ApiError {}

async function authHeaders(getToken: () => Promise<string>, demoUserId?: string) {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (demoUserId) {
    headers["X-Demo-User"] = demoUserId;
    headers["Authorization"] = "Bearer demo-token";
  } else {
    const token = await getToken();
    headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

export async function sendChatMessage(
  question: string,
  history: ChatMessage[],
  getToken: () => Promise<string>,
  demoUserId?: string,
  useLangGraph = false
): Promise<ChatResponse> {
  const endpoint = useLangGraph ? `${API_BASE}/chat/v2` : `${API_BASE}/chat`;
  const body = JSON.stringify({
    question,
    conversation_history: history.map((m) => ({ role: m.role, content: m.content })),
  });

  const attempt = async () => {
    const headers = await authHeaders(getToken, demoUserId);
    return fetch(endpoint, { method: "POST", headers, body });
  };

  let res = await attempt();

  // A 401 mid-session means the backend's cached On-Behalf-Of Graph token
  // (or the frontend's own access token) has expired. getToken() forces
  // MSAL to silently re-acquire a fresh token (or redirect to sign-in if
  // that's no longer possible — see App.tsx) — retry exactly once with
  // whatever it returns rather than surfacing a confusing error.
  if (res.status === 401 && !demoUserId) {
    res = await attempt();
  }

  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
    const message = errorBody.detail ?? `Request failed with ${res.status}`;
    if (errorBody.error_code === "obo_token_expired") {
      throw new SessionExpiredError(message, errorBody.error_code);
    }
    throw new ApiError(message, errorBody.error_code);
  }

  return res.json();
}
