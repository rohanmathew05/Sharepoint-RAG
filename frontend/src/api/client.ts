import type { ChatMessage, ChatResponse } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {}

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
  demoUserId?: string
): Promise<ChatResponse> {
  const body = JSON.stringify({
    question,
    conversation_history: history.map((m) => ({ role: m.role, content: m.content })),
  });

  const attempt = async () => {
    const headers = await authHeaders(getToken, demoUserId);
    return fetch(`${API_BASE}/chat`, { method: "POST", headers, body });
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
    throw new ApiError(errorBody.detail ?? `Request failed with ${res.status}`);
  }

  return res.json();
}
