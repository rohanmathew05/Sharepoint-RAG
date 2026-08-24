import type { ChatMessage, ChatStreamEvent, ConversationDetail, ConversationSummary } from "../types";

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

async function authHeaders(getToken: () => Promise<string>) {
  const token = await getToken();
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

// Always routes through the LangGraph pipeline (query rewriting +
// retrieval evaluation + intent classification) — see docs/LANGGRAPH.md.
const CHAT_STREAM_ENDPOINT = `${API_BASE}/chat/v2/stream`;

// The stream endpoint sends newline-delimited JSON, not SSE — EventSource
// can't carry the Authorization header this API requires, so this reads
// the fetch() response body as a stream and parses it by hand instead.
export async function streamChatMessage(
  question: string,
  history: ChatMessage[],
  conversationId: string | null,
  getToken: () => Promise<string>,
  onEvent: (event: ChatStreamEvent) => void
): Promise<void> {
  const body = JSON.stringify({
    question,
    conversation_history: history.map((m) => ({ role: m.role, content: m.content })),
    conversation_id: conversationId,
  });

  const attempt = async () => {
    const headers = await authHeaders(getToken);
    return fetch(CHAT_STREAM_ENDPOINT, { method: "POST", headers, body });
  };

  let res = await attempt();

  // Same terminal-401 retry as sendChatMessage: this only fires before
  // any streaming has begun (a stale frontend access token, rejected by
  // the auth dependency before the endpoint body runs) — a mid-stream
  // session expiry surfaces as an in-band {"type": "error"} event instead
  // (see backend/api/chat_v2.py), since the HTTP status is already
  // committed to 200 by the time that can happen.
  if (res.status === 401) {
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

  if (!res.body) {
    throw new ApiError("Streaming is not supported in this browser.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let newlineIndex: number;
    while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) onEvent(JSON.parse(line) as ChatStreamEvent);
    }
  }

  const rest = buffer.trim();
  if (rest) onEvent(JSON.parse(rest) as ChatStreamEvent);
}

const CONVERSATIONS_ENDPOINT = `${API_BASE}/conversations`;

async function jsonRequest<T>(
  url: string,
  init: RequestInit,
  getToken: () => Promise<string>
): Promise<T> {
  const headers = { ...(await authHeaders(getToken)), ...(init.headers ?? {}) };
  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    const errorBody = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(errorBody.detail ?? `Request failed with ${res.status}`, errorBody.error_code);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function listConversations(getToken: () => Promise<string>): Promise<ConversationSummary[]> {
  return jsonRequest(CONVERSATIONS_ENDPOINT, { method: "GET" }, getToken);
}

export function createConversation(getToken: () => Promise<string>): Promise<{ id: string }> {
  return jsonRequest(CONVERSATIONS_ENDPOINT, { method: "POST" }, getToken);
}

export function getConversation(
  id: string,
  getToken: () => Promise<string>
): Promise<ConversationDetail> {
  return jsonRequest(`${CONVERSATIONS_ENDPOINT}/${id}`, { method: "GET" }, getToken);
}

export function renameConversation(
  id: string,
  title: string,
  getToken: () => Promise<string>
): Promise<ConversationSummary> {
  return jsonRequest(
    `${CONVERSATIONS_ENDPOINT}/${id}`,
    { method: "PATCH", body: JSON.stringify({ title }) },
    getToken
  );
}

export function deleteConversation(id: string, getToken: () => Promise<string>): Promise<void> {
  return jsonRequest(`${CONVERSATIONS_ENDPOINT}/${id}`, { method: "DELETE" }, getToken);
}
