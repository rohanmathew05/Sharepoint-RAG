export interface Citation {
  document_id: string;
  document_name: string;
  web_url: string;
  is_folder: boolean;
  folder_path: string;
}

// Mirrors backend/models/chat.py's ReasoningStep — a real pipeline
// execution trace (which query was searched, whether it was judged
// relevant, etc.), not the model's token-level reasoning.
export interface ReasoningStep {
  kind: string;
  label: string;
  detail?: string | null;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  isError?: boolean;
  reasoningSteps?: ReasoningStep[];
  isStreaming?: boolean;
}

export interface ChatResponse {
  answer: string;
  citations: Citation[];
  retrieval_attempts: number;
  reasoning_steps: ReasoningStep[];
}

// Events sent by POST /api/chat/v2/stream, one JSON object per line
// (newline-delimited, not SSE — see api/client.ts's streamChatMessage for
// why: EventSource can't carry an Authorization header, and this needs
// the caller's MSAL bearer token).
export type ChatStreamEvent =
  | { type: "step"; step: ReasoningStep }
  | { type: "token"; text: string }
  | {
      type: "done";
      answer: string;
      citations: Citation[];
      retrieval_attempts: number;
    }
  | { type: "error"; error_code: string | null; detail: string };
