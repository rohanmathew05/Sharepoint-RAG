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
  const headers = await authHeaders(getToken, demoUserId);
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      question,
      conversation_history: history.map((m) => ({ role: m.role, content: m.content })),
    }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(body.detail ?? `Request failed with ${res.status}`);
  }

  return res.json();
}
